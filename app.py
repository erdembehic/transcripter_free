import logging
import os
import secrets
import shutil
import time
from datetime import timedelta

import av
from flask import Flask, Response, abort, jsonify, render_template, request, session

import jobs
import transcriber

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

UPLOAD_DIR = "uploads"
AD_SECONDS = int(os.environ.get("AD_SECONDS", "30"))
MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "500"))
# Gerçek reklam ağı eklerken alan adlarını buraya ekleyin (boşlukla ayrılmış),
# örn. "https://pagead2.googlesyndication.com https://*.doubleclick.net"
AD_CSP_SOURCES = os.environ.get("AD_CSP_SOURCES", "")
ALLOWED_EXTENSIONS = {
    "mp3", "wav", "m4a", "aac", "ogg", "oga", "opus", "flac", "wma", "amr",
    "mp4", "m4v", "mkv", "mov", "avi", "webm", "wmv", "flv", "3gp", "mpeg", "mpg", "ts",
}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE") == "1",  # HTTPS arkasında 1 yapın
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    # Çerez yalnızca oturum değişince yazılsın; aynı anda giden isteklerin
    # birbirinin çerezini ezmesini önler
    SESSION_REFRESH_EACH_REQUEST=False,
)

# Önceki çalıştırmadan kalan yüklemeler (işler bellekte tutulduğu için sahipsiz kalırlar)
shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
jobs.start_workers()


def error(message, status):
    return jsonify({"error": message}), status


@app.before_request
def protect():
    if not session.permanent:
        session.permanent = True
    # Basit CSRF koruması: başka sitelerden gelen formlar bu başlığı ekleyemez
    if request.method == "POST" and request.headers.get("X-Requested-With") != "fetch":
        abort(403)


@app.after_request
def security_headers(resp):
    extra = f" {AD_CSP_SOURCES}" if AD_CSP_SOURCES else ""
    resp.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src 'self'{extra}; img-src 'self' data:{extra}; "
        f"frame-src 'self'{extra}; connect-src 'self'{extra}; style-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.errorhandler(413)
def too_large(_):
    return error(f"Dosya en fazla {MAX_UPLOAD_MB} MB olabilir.", 413)


def owned_job(job_id):
    """İşe yalnızca onu oluşturan tarayıcı (imzalı oturum çerezi) erişebilir."""
    job = jobs.get(job_id)
    if not job or job_id not in session.get("jobs", []):
        abort(404)
    return job


def ad_watched(purpose):
    """Sunucu tarafında reklamın gerçekten izlendiğini doğrular ve hakkı tüketir."""
    ad = session.get("ad")
    # Ağ gecikmesi için 1 sn tolerans
    if not ad or ad.get("for") != purpose or time.time() - ad["t"] < AD_SECONDS - 1:
        return False
    session.pop("ad")
    return True


def has_audio(path):
    try:
        with av.open(path) as container:
            return any(s.type == "audio" for s in container.streams)
    except Exception:
        return False


@app.route("/")
def index():
    return render_template("index.html", ad_seconds=AD_SECONDS, max_mb=MAX_UPLOAD_MB)


@app.post("/api/ads")
def start_ad():
    purpose = (request.get_json(silent=True) or {}).get("for", "start")
    if purpose != "start":
        owned_job(purpose)
    session["ad"] = {"for": purpose, "t": time.time()}
    return jsonify({"seconds": AD_SECONDS})


@app.post("/api/jobs")
def create_job():
    file = request.files.get("file")
    if not file or not file.filename:
        return error("Dosya seçin.", 400)
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        return error("Desteklenmeyen dosya türü.", 400)
    try:
        language = transcriber.normalize_language(request.form.get("language"))
    except ValueError:
        return error("Desteklenmeyen dil.", 400)

    # Kullanıcının verdiği dosya adı diskte hiç kullanılmaz
    path = os.path.join(UPLOAD_DIR, f"{secrets.token_hex(16)}.{ext}")
    file.save(path)
    if not has_audio(path):
        os.remove(path)
        return error("Dosyada ses bulunamadı.", 400)
    try:
        job = jobs.create(path, language)
    except OverflowError:
        os.remove(path)
        return error("Sunucu şu an çok yoğun, birazdan tekrar deneyin.", 503)

    session["jobs"] = (session.get("jobs", []) + [job.id])[-20:]
    return jsonify(job.public()), 201


@app.post("/api/jobs/<job_id>/start")
def start_job(job_id):
    job = owned_job(job_id)
    if job.state == "pending":
        if not ad_watched("start"):
            return error("Önce reklamın bitmesini bekleyin.", 403)
        runs = session.get("runs", 0)
        session["runs"] = runs + 1
        jobs.start(job, needs_end_ad=runs >= 1)  # ilk kullanımdan sonra sonda da reklam
    return jsonify(job.public())


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    return jsonify(owned_job(job_id).public())


@app.get("/api/jobs/<job_id>/result")
def job_result(job_id):
    job = owned_job(job_id)
    if job.state != "done":
        return error("Sonuç henüz hazır değil.", 409)
    if not job.unlocked:
        if not ad_watched(job.id):
            return error("Önce reklamın bitmesini bekleyin.", 403)
        job.unlocked = True
    fmt = request.args.get("format", "txt")
    if fmt not in transcriber.FORMATS:
        return error("Geçersiz format.", 400)
    render, mimetype = transcriber.FORMATS[fmt]
    resp = Response(render(job.segments), mimetype=f"{mimetype}; charset=utf-8")
    if request.args.get("download"):
        resp.headers["Content-Disposition"] = f'attachment; filename="{job.id}.{fmt}"'
    resp.headers["Cache-Control"] = "no-store"
    return resp


if __name__ == "__main__":
    from waitress import serve

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    log.info("http://%s:%s adresinde çalışıyor", host, port)
    # Model bellekte tek kopya tutulduğu için tek süreç + birkaç thread kullanılır
    serve(app, host=host, port=port, threads=8)

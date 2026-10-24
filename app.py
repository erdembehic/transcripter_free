import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, send_file

import transcriber

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", BASE_DIR / "output"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "500"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))
RESULT_TTL_SECONDS = int(os.getenv("RESULT_TTL_SECONDS", "3600"))

ALLOWED_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv", ".m4v",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wma",
}
OUTPUT_FORMATS = {"txt": "text/plain", "srt": "application/x-subrip"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
jobs = {}
jobs_lock = threading.Lock()


def _update(job_id, **fields):
    with jobs_lock:
        jobs[job_id].update(fields)


def _snapshot(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
        return dict(job) if job else None


def _run_job(job_id, upload_path, lang):
    _update(job_id, status="running")
    try:
        segments = transcriber.transcribe(
            upload_path, lang, on_progress=lambda p: _update(job_id, progress=p)
        )
        (OUTPUT_DIR / f"{job_id}.txt").write_text(transcriber.segments_to_text(segments), encoding="utf-8")
        (OUTPUT_DIR / f"{job_id}.srt").write_text(transcriber.segments_to_srt(segments), encoding="utf-8")
        _update(job_id, status="done", progress=100, finished=time.time())
    except transcriber.TranscriptionError as exc:
        _update(job_id, status="error", error=str(exc), finished=time.time())
    except Exception:
        app.logger.exception("Transkripsiyon başarısız: %s", job_id)
        _update(job_id, status="error", error="Beklenmeyen bir hata oluştu.", finished=time.time())
    finally:
        upload_path.unlink(missing_ok=True)


def _cleanup_expired():
    cutoff = time.time() - RESULT_TTL_SECONDS
    with jobs_lock:
        expired = [jid for jid, job in jobs.items()
                   if job.get("finished") and job["finished"] < cutoff]
        for jid in expired:
            del jobs[jid]
    for jid in expired:
        for fmt in OUTPUT_FORMATS:
            (OUTPUT_DIR / f"{jid}.{fmt}").unlink(missing_ok=True)


def _error(message, status):
    return jsonify({"error": message}), status


@app.errorhandler(413)
def too_large(_):
    return _error(f"Dosya çok büyük (en fazla {MAX_UPLOAD_MB} MB).", 413)


@app.route("/")
def index():
    return render_template("index.html", language_groups=transcriber.LANGUAGE_GROUPS,
                           max_upload_mb=MAX_UPLOAD_MB)


@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("file")
    lang = request.form.get("option", "")
    if not file or not file.filename:
        return _error("Dosya seçilmedi.", 400)
    if lang not in transcriber.LANGUAGES:
        return _error("Geçersiz dil seçimi.", 400)
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return _error(f"Desteklenmeyen dosya türü: {ext or 'uzantısız'}", 400)

    _cleanup_expired()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    upload_path = UPLOAD_DIR / f"{job_id}{ext}"
    file.save(upload_path)

    with jobs_lock:
        jobs[job_id] = {
            "status": "queued", "progress": 0, "error": None, "language": lang,
            "name": Path(file.filename).stem or "transkript", "created": time.time(),
        }
    executor.submit(_run_job, job_id, upload_path, lang)
    return jsonify({"job_id": job_id, "language": lang})


def _public(job):
    return {k: job[k] for k in ("status", "progress", "error")}


@app.route("/status/<job_id>")
def status(job_id):
    job = _snapshot(job_id)
    if not job:
        return _error("İş bulunamadı.", 404)
    return jsonify(_public(job))


@app.route("/progress/<job_id>")
def progress(job_id):
    if not _snapshot(job_id):
        return _error("İş bulunamadı.", 404)

    def stream():
        last = None
        while True:
            job = _snapshot(job_id)
            if not job:
                yield f"data: {json.dumps({'status': 'error', 'progress': 0, 'error': 'İş bulunamadı.'})}\n\n"
                return
            state = _public(job)
            if state != last:
                last = state
                yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
            if state["status"] in ("done", "error"):
                return
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/download/<job_id>")
def download(job_id):
    fmt = request.args.get("format", "txt")
    if fmt not in OUTPUT_FORMATS:
        return _error("Geçersiz format.", 400)
    job = _snapshot(job_id)
    if not job:
        return _error("İş bulunamadı.", 404)
    if job["status"] != "done":
        return _error("Dosya henüz hazır değil.", 409)
    path = OUTPUT_DIR / f"{job_id}.{fmt}"
    if not path.exists():
        abort(404)
    return send_file(path, as_attachment=request.args.get("inline") != "1",
                     download_name=f"{job['name']}.{fmt}", mimetype=OUTPUT_FORMATS[fmt])


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG") == "1", threaded=True)

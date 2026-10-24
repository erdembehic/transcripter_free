"""Vosk ile medya dosyalarını yazıya çeviren çekirdek modül.

Ses, ffmpeg ile doğrudan 16 kHz mono PCM olarak okunur (geçici WAV dosyası
oluşturulmaz). Vosk modelleri dil başına bir kez yüklenip önbellekte tutulur.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

import vosk

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # 16-bit mono
CHUNK_BYTES = BYTES_PER_SECOND // 2  # ~0.5 saniyelik ses
MAX_WORDS_PER_CUE = 10

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = Path(os.getenv("MODELS_DIR", BASE_DIR / "models"))

# Arayüzde gösterilen diller: (grup, [(kod, ad), ...])
LANGUAGE_GROUPS = [
    ("Asya Dilleri", [
        ("tr", "Türkçe"), ("hi", "Hintçe"), ("ko", "Korece"), ("ja", "Japonca"),
        ("cn", "Çince"), ("uz", "Özbekçe"), ("kz", "Kazakça"), ("tg", "Tacikçe"),
    ]),
    ("Avrupa Dilleri", [
        ("en-us", "İngilizce (US)"), ("en-gb", "İngilizce (UK)"), ("fr", "Fransızca"),
        ("de", "Almanca"), ("it", "İtalyanca"), ("es", "İspanyolca"), ("pt", "Portekizce"),
        ("ru", "Rusça"), ("pl", "Lehçe"), ("nl", "Flemenkçe"), ("sv", "İsveççe"),
        ("cs", "Çekçe"), ("el-gr", "Yunanca"), ("br", "Bretonca"), ("ua", "Ukraynaca"),
        ("ca", "Katalanca"),
    ]),
    ("Orta Doğu ve Diğer", [
        ("ar", "Arapça"), ("ar-tn", "Tunus Arapçası"), ("fa", "Farsça"), ("he", "İbranice"),
        ("eo", "Esperanto"), ("gu", "Gujarati"), ("te", "Telugu"), ("tl-ph", "Filipince"),
        ("vn", "Vietnamca"),
    ]),
]
LANGUAGES = {code for _, langs in LANGUAGE_GROUPS for code, _ in langs}

vosk.SetLogLevel(-1)

_models = {}
_model_locks = {}
_registry_lock = threading.Lock()


class TranscriptionError(Exception):
    """Kullanıcıya gösterilebilecek bir hata mesajı taşır."""


def _find_local_model(lang):
    pattern = re.compile(rf"^vosk-model(-small)?-{re.escape(lang)}(-|$)")
    for directory in (MODELS_DIR, BASE_DIR):
        if not directory.is_dir():
            continue
        # Küçük modeller daha hızlı yüklenir; varsa önce onları seç
        candidates = sorted(p for p in directory.iterdir() if p.is_dir() and pattern.match(p.name))
        candidates.sort(key=lambda p: "-small-" not in p.name)
        if candidates:
            return candidates[0]
    return None


def get_model(lang):
    """Dilin modelini döndürür; ilk çağrıda yükler, sonra önbellekten verir."""
    if lang not in LANGUAGES:
        raise TranscriptionError(f"Desteklenmeyen dil: {lang}")
    with _registry_lock:
        if lang in _models:
            return _models[lang]
        lock = _model_locks.setdefault(lang, threading.Lock())
    with lock:
        if lang in _models:
            return _models[lang]
        local = _find_local_model(lang)
        try:
            if local:
                model = vosk.Model(str(local))
            else:
                # Yerelde yoksa Vosk küçük modeli ~/.cache/vosk altına indirir
                model = vosk.Model(lang=lang)
        except (Exception, SystemExit) as exc:
            # vosk, bilinmeyen dilde sys.exit() çağırıyor; işçi thread'i ölmesin
            raise TranscriptionError(
                f"'{lang}' modeli yüklenemedi. Modeli indirip {MODELS_DIR} klasörüne çıkarın."
            ) from exc
        _models[lang] = model
        return model


def _require_ffmpeg():
    if not shutil.which("ffmpeg"):
        raise TranscriptionError("ffmpeg bulunamadı. Lütfen ffmpeg kurun ve PATH'e ekleyin.")


def probe_duration(path):
    """Medya süresini saniye olarak döndürür; okunamazsa None."""
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        duration = float(out)
        return duration if duration > 0 else None
    except (ValueError, subprocess.SubprocessError):
        return None


def _words_to_segments(words):
    """Vosk kelime listesini en fazla MAX_WORDS_PER_CUE kelimelik parçalara böler."""
    segments = []
    for i in range(0, len(words), MAX_WORDS_PER_CUE):
        chunk = words[i:i + MAX_WORDS_PER_CUE]
        segments.append({
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "text": " ".join(w["word"] for w in chunk),
        })
    return segments


def transcribe(path, lang, on_progress=None):
    """Dosyayı yazıya çevirir ve zaman damgalı parçaların listesini döndürür.

    on_progress(yüzde) çağrısı, süre biliniyorsa 0-99 arası değerlerle yapılır.
    """
    _require_ffmpeg()
    model = get_model(lang)
    duration = probe_duration(path)
    expected_bytes = duration * BYTES_PER_SECOND if duration else None

    rec = vosk.KaldiRecognizer(model, SAMPLE_RATE)
    rec.SetWords(True)
    segments = []

    def collect(result_json):
        words = json.loads(result_json).get("result", [])
        if words:
            segments.extend(_words_to_segments(words))

    # stderr'i dosyaya yazıyoruz; PIPE dolarsa ffmpeg kilitlenebilir
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
             "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=err,
        )
        read = 0
        last_percent = -1
        try:
            while True:
                data = proc.stdout.read(CHUNK_BYTES)
                if not data:
                    break
                read += len(data)
                if rec.AcceptWaveform(data):
                    collect(rec.Result())
                if on_progress and expected_bytes:
                    percent = min(99, int(read * 100 / expected_bytes))
                    if percent != last_percent:
                        last_percent = percent
                        on_progress(percent)
        finally:
            proc.stdout.close()
            returncode = proc.wait()
        if returncode != 0:
            err.seek(0)
            detail = err.read().decode("utf-8", "replace").strip().splitlines()
            raise TranscriptionError(
                "Medya dosyası okunamadı" + (f": {detail[-1]}" if detail else ".")
            )
    collect(rec.FinalResult())
    return segments


def segments_to_text(segments):
    return " ".join(s["text"] for s in segments).strip() + "\n"


def _srt_time(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments):
    blocks = [
        f"{i}\n{_srt_time(s['start'])} --> {_srt_time(s['end'])}\n{s['text']}\n"
        for i, s in enumerate(segments, 1)
    ]
    return "\n".join(blocks)

import logging
import os
import threading

import ctranslate2
from faster_whisper import BatchedInferencePipeline, WhisperModel
from faster_whisper.tokenizer import _LANGUAGE_CODES

log = logging.getLogger(__name__)

HAS_CUDA = ctranslate2.get_cuda_device_count() > 0

# Ayarlar ortam değişkenleriyle değiştirilebilir
MODEL_SIZE = os.environ.get("WHISPER_MODEL") or ("turbo" if HAS_CUDA else "small")
DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # auto, cpu, cuda
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE") or ("float16" if HAS_CUDA else "int8")
BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "5"))
# 0 = toplu (batched) mod kapalı. Toplu mod özellikle GPU'da 3-4 kat hızlıdır.
BATCH_SIZE = int(os.environ.get("WHISPER_BATCH_SIZE") or (16 if HAS_CUDA else 8))
CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "0"))  # 0 = otomatik

LANGUAGES = set(_LANGUAGE_CODES)

_model = None
_pipeline = None
_model_lock = threading.Lock()


def get_model():
    """Modeli yalnızca bir kez yükler ve tüm istekler için tekrar kullanır."""
    global _model, _pipeline
    if _model is None:
        with _model_lock:
            if _model is None:
                log.info("Model yükleniyor: %s (%s, %s)", MODEL_SIZE, DEVICE, COMPUTE_TYPE)
                model = WhisperModel(MODEL_SIZE, device=DEVICE,
                                     compute_type=COMPUTE_TYPE, cpu_threads=CPU_THREADS)
                _pipeline = BatchedInferencePipeline(model=model) if BATCH_SIZE > 0 else None
                _model = model
                log.info("Model hazır")
    return _model


def normalize_language(language):
    """'auto'/boş -> None (otomatik algılama). Bilinmeyen kod -> ValueError."""
    if not language or language == "auto":
        return None
    language = language.lower()
    if language not in LANGUAGES:
        raise ValueError(f"Desteklenmeyen dil: {language}")
    return language


def transcribe(media_path, language=None):
    """(segment üreteci, bilgi) döndürür. Ses PyAV ile doğrudan videodan çözülür."""
    model = get_model()
    language = normalize_language(language)
    if _pipeline is not None:
        return _pipeline.transcribe(media_path, language=language,
                                    beam_size=BEAM_SIZE, batch_size=BATCH_SIZE)
    return model.transcribe(
        media_path,
        language=language,
        beam_size=BEAM_SIZE,
        vad_filter=True,  # sessiz kısımları atlar
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,  # tekrar eden halüsinasyonları azaltır
    )


def _timestamp(seconds, sep):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_txt(segments):
    return "\n".join(s["text"] for s in segments) + "\n"


def to_srt(segments):
    return "".join(
        f"{i}\n{_timestamp(s['start'], ',')} --> {_timestamp(s['end'], ',')}\n{s['text']}\n\n"
        for i, s in enumerate(segments, start=1))


def to_vtt(segments):
    return "WEBVTT\n\n" + "".join(
        f"{_timestamp(s['start'], '.')} --> {_timestamp(s['end'], '.')}\n{s['text']}\n\n"
        for s in segments)


FORMATS = {
    "txt": (to_txt, "text/plain"),
    "srt": (to_srt, "application/x-subrip"),
    "vtt": (to_vtt, "text/vtt"),
}

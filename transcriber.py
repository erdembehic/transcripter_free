import os
import threading

from faster_whisper import WhisperModel

# Ayarlar ortam değişkenleriyle değiştirilebilir
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")  # tiny, base, small, medium, large-v3, turbo
DEVICE = os.environ.get("WHISPER_DEVICE", "auto")  # auto, cpu, cuda
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "default")  # CPU'da int8, GPU'da float16 seçilir
BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "5"))
CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "0"))  # 0 = otomatik

OUTPUT_DIR = "output"

# Arayüzdeki (Vosk tarzı) dil kodlarını Whisper kodlarına çevir
LANGUAGE_MAP = {
    "en-us": "en",
    "en-gb": "en",
    "cn": "zh",
    "kz": "kk",
    "ua": "uk",
    "el-gr": "el",
    "ar-tn": "ar",
    "tl-ph": "tl",
    "vn": "vi",
    "all": None,  # otomatik algılama
    "auto": None,
}

_model = None
_model_lock = threading.Lock()
# Aynı modeli eşzamanlı isteklerde paylaşmak yerine sırayla çalıştır (bellek patlamasını önler)
_transcribe_lock = threading.Lock()


def get_model():
    """Modeli yalnızca bir kez yükler ve tüm istekler için tekrar kullanır."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                compute_type = COMPUTE_TYPE
                if compute_type == "default":
                    compute_type = "auto"
                if DEVICE == "cpu" and compute_type == "auto":
                    compute_type = "int8"
                _model = WhisperModel(
                    MODEL_SIZE,
                    device=DEVICE,
                    compute_type=compute_type,
                    cpu_threads=CPU_THREADS,
                )
    return _model


def to_whisper_language(language):
    if not language:
        return None
    language = language.lower()
    if language in LANGUAGE_MAP:
        return LANGUAGE_MAP[language]
    return language.split("-")[0]


def _format_timestamp(seconds):
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _sse(data):
    return f"data: {data}\n\n"


def transcribe(media_path, language=None):
    """Segment üreteci ve bilgi döndürür. faster-whisper sesi PyAV ile doğrudan
    videodan çözer, ayrıca ffmpeg ile WAV'a çevirmeye gerek yoktur."""
    model = get_model()
    return model.transcribe(
        media_path,
        language=to_whisper_language(language),
        beam_size=BEAM_SIZE,
        vad_filter=True,  # sessiz kısımları atlar, ciddi hız kazancı sağlar
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,  # tekrar eden halüsinasyonları azaltır
    )


def run_whisper_and_stream_progress(media_path, language=None, stream=True):
    """Transkripsiyonu yapar, SSE formatında ilerleme yüzdesi yayınlar ve
    bittiğinde '__DONE__|<dosya>' gönderir. Çıktı .txt ve .srt olarak yazılır."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    base = os.path.splitext(os.path.basename(media_path))[0]
    txt_name = f"{base}.txt"
    srt_name = f"{base}.srt"

    yield _sse("0")
    try:
        with _transcribe_lock:
            segments, info = transcribe(media_path, language)
            duration = info.duration or 0
            last_percent = -1

            txt_path = os.path.join(OUTPUT_DIR, txt_name)
            srt_path = os.path.join(OUTPUT_DIR, srt_name)
            with open(txt_path + ".part", "w", encoding="utf-8") as txt, \
                    open(srt_path, "w", encoding="utf-8") as srt:
                for i, seg in enumerate(segments, start=1):
                    text = seg.text.strip()
                    txt.write(text + "\n")
                    srt.write(f"{i}\n{_format_timestamp(seg.start)} --> "
                              f"{_format_timestamp(seg.end)}\n{text}\n\n")
                    if duration:
                        percent = min(99.0, round(seg.end / duration * 100, 1))
                        if percent != last_percent:
                            last_percent = percent
                            yield _sse(percent)
            # İndirme yalnızca dosya tamamen yazıldığında mümkün olsun
            os.replace(txt_path + ".part", txt_path)

        yield _sse("100")
        yield _sse(f"__DONE__|{txt_name}")
    except Exception as e:
        yield _sse(f"__ERROR__|{e}")
    finally:
        try:
            os.remove(media_path)
        except OSError:
            pass

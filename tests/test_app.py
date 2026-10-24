import io
import json
import subprocess
import time

import pytest

import app as app_module
import transcriber


class FakeRecognizer:
    """Gerçek model olmadan Vosk tanıyıcısını taklit eder: her saniyeye bir kelime."""

    def __init__(self, model, rate):
        self.bytes = 0
        self.words = []

    def SetWords(self, enabled):
        pass

    def AcceptWaveform(self, data):
        before = self.bytes // transcriber.BYTES_PER_SECOND
        self.bytes += len(data)
        after = self.bytes // transcriber.BYTES_PER_SECOND
        for sec in range(before, after):
            self.words.append({"word": f"kelime{sec}", "start": float(sec), "end": sec + 0.5})
        return len(self.words) >= 3

    def _flush(self):
        words, self.words = self.words, []
        return json.dumps({"result": words, "text": " ".join(w["word"] for w in words)})

    Result = _flush
    FinalResult = _flush


@pytest.fixture
def fake_vosk(monkeypatch):
    monkeypatch.setattr(transcriber, "get_model", lambda lang: object())
    monkeypatch.setattr(transcriber.vosk, "KaldiRecognizer", FakeRecognizer)


@pytest.fixture
def audio_file(tmp_path):
    path = tmp_path / "ses.wav"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=5",
         "-ar", "44100", str(path)],
        check=True,
    )
    return path


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")
    app_module.jobs.clear()
    return app_module.app.test_client()


def wait_for_job(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get(f"/status/{job_id}").get_json()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.05)
    raise AssertionError("İş zamanında bitmedi")


def test_transcribe_reports_progress_and_segments(fake_vosk, audio_file):
    progress = []
    segments = transcriber.transcribe(audio_file, "tr", on_progress=progress.append)
    assert [s["text"] for s in segments] == ["kelime0 kelime1 kelime2", "kelime3 kelime4"]
    assert progress == sorted(progress) and progress[-1] >= 90


def test_transcribe_rejects_unreadable_media(fake_vosk, tmp_path):
    bad = tmp_path / "bozuk.mp4"
    bad.write_bytes(b"bu bir video degil")
    with pytest.raises(transcriber.TranscriptionError, match="okunamadı"):
        transcriber.transcribe(bad, "tr")


def test_srt_format():
    srt = transcriber.segments_to_srt([
        {"start": 0.0, "end": 1.25, "text": "merhaba"},
        {"start": 3661.5, "end": 3662.0, "text": "dünya"},
    ])
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,250\nmerhaba\n\n"
        "2\n01:01:01,500 --> 01:01:02,000\ndünya\n"
    )


def test_find_local_model_prefers_exact_language(tmp_path, monkeypatch):
    for name in ("vosk-model-small-ar-tn-0.1", "vosk-model-ar-0.22", "vosk-model-small-ar-0.3"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(transcriber, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(transcriber, "BASE_DIR", tmp_path / "yok")
    assert transcriber._find_local_model("ar").name == "vosk-model-small-ar-0.3"
    assert transcriber._find_local_model("ar-tn").name == "vosk-model-small-ar-tn-0.1"
    assert transcriber._find_local_model("tr") is None


@pytest.mark.parametrize("data, message", [
    ({"option": "tr"}, "Dosya seçilmedi"),
    ({"option": "xx", "file": (io.BytesIO(b"x"), "a.mp4")}, "Geçersiz dil"),
    ({"option": "tr", "file": (io.BytesIO(b"x"), "a.exe")}, "Desteklenmeyen dosya"),
])
def test_upload_validation(client, data, message):
    res = client.post("/upload", data=data, content_type="multipart/form-data")
    assert res.status_code == 400
    assert message in res.get_json()["error"]


def test_full_flow(client, fake_vosk, audio_file):
    with open(audio_file, "rb") as f:
        res = client.post("/upload", data={"option": "tr", "file": (f, "Toplantı kaydı.wav")},
                          content_type="multipart/form-data")
    job_id = res.get_json()["job_id"]
    assert wait_for_job(client, job_id)["status"] == "done"

    events = client.get(f"/progress/{job_id}").get_data(as_text=True)
    assert '"status": "done"' in events

    txt = client.get(f"/download/{job_id}?format=txt")
    assert txt.status_code == 200
    assert txt.get_data(as_text=True).startswith("kelime0 kelime1")
    assert "Toplant" in txt.headers["Content-Disposition"]
    srt = client.get(f"/download/{job_id}?format=srt").get_data(as_text=True)
    assert srt.startswith("1\n00:00:00,000 --> ")
    assert not list(app_module.UPLOAD_DIR.iterdir()), "yüklenen dosya silinmeli"


def test_failed_job_reports_error(client, fake_vosk):
    res = client.post("/upload", data={"option": "tr", "file": (io.BytesIO(b"bozuk"), "a.mp4")},
                      content_type="multipart/form-data")
    state = wait_for_job(client, res.get_json()["job_id"])
    assert state["status"] == "error" and "okunamadı" in state["error"]


@pytest.mark.parametrize("url", [
    "/download/..%2F..%2Fapp.py",
    "/download/yok",
    "/download/yok?format=../../app",
    "/progress/yok",
])
def test_unknown_or_malicious_ids_are_rejected(client, url):
    assert client.get(url).status_code in (400, 404)

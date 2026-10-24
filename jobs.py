"""Arka plan iş kuyruğu. İşler tarayıcı bağlantısından bağımsız çalışır;
sayfa yenilense de iş devam eder ve aynı iş adıyla tekrar bağlanılabilir."""
import logging
import os
import queue
import secrets
import threading
import time
from dataclasses import dataclass, field

import transcriber

log = logging.getLogger(__name__)

RESULT_TTL = int(os.environ.get("RESULT_TTL_SECONDS", "3600"))  # sonuçlar bu süre sonra silinir
PENDING_TTL = 15 * 60  # yüklenip başlatılmayan işler
MAX_QUEUE = int(os.environ.get("MAX_QUEUE", "20"))

# Docker'ın konteyner adları gibi: sıfat_bilim-insanı
ADJECTIVES = """
admiring adoring agitated amazing angry awesome blissful bold boring brave busy
charming clever cool compassionate competent confident cranky dazzling determined
distracted dreamy eager ecstatic elastic elated elegant eloquent epic fervent
festive flamboyant focused friendly frosty funny gallant gifted goofy gracious
happy hardcore heuristic hopeful hungry infallible inspiring intelligent jolly
jovial keen kind laughing loving lucid magical modest musing mystifying naughty
nervous nice nifty nostalgic objective optimistic peaceful pedantic pensive
practical priceless quirky quizzical recursing relaxed reverent romantic sad
serene sharp silly sleepy stoic strange stupefied suspicious sweet tender
thirsty trusting unruffled upbeat vibrant vigilant vigorous wizardly wonderful
xenodochial youthful zealous zen
""".split()

NAMES = """
albattani allen archimedes ardinghelli aryabhata babbage banach bardeen bartik
bassi bell benz bhabha bohr booth bose brahmagupta brown burnell cannon carson
cerf chandrasekhar chebyshev clarke cohen colden cori curie darwin davinci
dijkstra dirac einstein elion engelbart euclid euler fermat fermi feynman
franklin galileo gauss goldberg goodall hamilton hawking heisenberg hertz hopper
hypatia jackson jang jemison johnson kalam kepler khayyam knuth kowalevski
lalande lamarr leakey leavitt lovelace lumiere mayer mccarthy mclean meitner
mendel mirzakhani morse newton nobel noether pascal pasteur payne perlman pike
poincare ptolemy raman ramanujan ride ritchie roentgen rosalind sagan saha
shannon shockley sinoussi snyder stallman stonebraker swanson tesla thompson
torvalds turing varahamihira visvesvaraya volhard wescoff wiles williams wilson
wozniak wright yalow yonath
""".split()


@dataclass
class Job:
    id: str
    path: str
    language: str | None
    state: str = "pending"  # pending -> queued -> running -> done | error
    progress: float = 0.0
    needs_end_ad: bool = False
    unlocked: bool = True
    segments: list = field(default_factory=list)
    detected_language: str | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    def public(self):
        return {"id": self.id, "state": self.state, "progress": round(self.progress, 1),
                "needs_end_ad": self.needs_end_ad and not self.unlocked,
                "error": self.error}


_jobs: dict[str, Job] = {}
_lock = threading.Lock()
_queue: "queue.Queue[str]" = queue.Queue()


def _new_id():
    for attempt in range(100):
        name = f"{secrets.choice(ADJECTIVES)}_{secrets.choice(NAMES)}"
        if attempt > 10:  # isim alanı dolmaya başladıysa sayı ekle
            name += str(secrets.randbelow(100))
        if name not in _jobs:
            return name
    raise RuntimeError("İş adı üretilemedi")


def create(path, language):
    with _lock:
        if sum(j.state in ("pending", "queued", "running") for j in _jobs.values()) >= MAX_QUEUE:
            raise OverflowError("Kuyruk dolu")
        job = Job(id=_new_id(), path=path, language=language)
        _jobs[job.id] = job
    return job


def get(job_id):
    return _jobs.get(job_id)


def start(job, needs_end_ad):
    with _lock:
        if job.state != "pending":
            return
        job.state = "queued"
        job.needs_end_ad = needs_end_ad
        job.unlocked = not needs_end_ad
    _queue.put(job.id)


def _remove_file(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _run(job):
    job.state = "running"
    try:
        segments, info = transcriber.transcribe(job.path, job.language)
        job.detected_language = info.language
        duration = info.duration or 0
        for seg in segments:
            job.segments.append({"start": seg.start, "end": seg.end, "text": seg.text.strip()})
            if duration:
                job.progress = min(99.0, seg.end / duration * 100)
        job.progress = 100.0
        job.state = "done"
    except Exception:
        log.exception("Transkripsiyon başarısız: %s", job.id)
        job.error = "Dosya işlenemedi. Lütfen başka bir dosya deneyin."
        job.state = "error"
    finally:
        job.finished = time.time()
        _remove_file(job.path)


def _worker():
    transcriber.get_model()  # modeli sunucu açılırken önceden yükle
    while True:
        job = get(_queue.get())
        if job:
            _run(job)


def _cleanup():
    while True:
        time.sleep(60)
        now = time.time()
        with _lock:
            expired = [j for j in _jobs.values()
                       if (j.state == "pending" and now - j.created > PENDING_TTL)
                       or (j.finished and now - j.finished > RESULT_TTL)]
            for j in expired:
                del _jobs[j.id]
        for j in expired:
            _remove_file(j.path)


def start_workers():
    threading.Thread(target=_worker, daemon=True, name="whisper-worker").start()
    threading.Thread(target=_cleanup, daemon=True, name="cleanup").start()

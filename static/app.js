(() => {
  const AD_SECONDS = Number(document.body.dataset.adSeconds);
  const MAX_MB = Number(document.body.dataset.maxMb);
  const UPLOAD_SHARE = 15; // yükleme, ilerleme çubuğunun ilk %15'i
  const $ = (id) => document.getElementById(id);

  const fileInput = $("file");
  const drop = $("drop");

  // --- Yardımcılar ---------------------------------------------------------

  const store = {
    get() { try { return localStorage.getItem("job"); } catch { return null; } },
    set(id) { try { localStorage.setItem("job", id); } catch {} },
    clear() { try { localStorage.removeItem("job"); } catch {} },
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function api(path, options = {}) {
    const res = await fetch(path, {
      ...options,
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch", ...(options.headers || {}) },
    });
    const isJson = (res.headers.get("Content-Type") || "").includes("json");
    const body = isJson ? await res.json() : await res.text();
    if (!res.ok) {
      const err = new Error((isJson && body.error) || "Bir hata oluştu.");
      err.status = res.status;
      throw err;
    }
    return body;
  }

  function show(section) {
    for (const id of ["form", "progress", "result"]) $(id).hidden = id !== section;
  }

  function showError(msg) {
    $("error").textContent = msg;
    $("error").hidden = !msg;
  }

  function setProgress(p) {
    p = Math.max(0, Math.min(100, p));
    $("barFill").style.width = p + "%";
    $("percent").textContent = "%" + Math.floor(p);
  }

  function setJobName(id) {
    document.querySelectorAll(".jobName").forEach((el) => (el.textContent = id || ""));
  }

  // --- Tam ekran reklam ----------------------------------------------------

  let closeAd = null;

  // Reklamı sunucuya kaydeder, gösterir ve { closed } döndürür.
  // Oturum çerezde tutulduğu için istekler aynı anda değil sırayla gönderilir.
  async function showAd(purpose) {
    await api("/api/ads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ for: purpose }),
    });
    const overlay = $("interstitial");
    const count = $("adCount");
    const closeBtn = $("adClose");
    overlay.hidden = false;
    closeBtn.hidden = true;
    count.hidden = false;

    const closed = new Promise((resolve) => {
      let left = AD_SECONDS;
      count.textContent = left;
      const timer = setInterval(() => {
        if (document.hidden) return; // sekme görünmüyorsa süre durur
        left -= 1;
        count.textContent = left;
        if (left <= 0) {
          clearInterval(timer);
          count.hidden = true;
          closeBtn.hidden = false;
        }
      }, 1000);
      closeAd = () => {
        clearInterval(timer);
        overlay.hidden = true;
        closeAd = null;
        resolve();
      };
      closeBtn.onclick = closeAd;
    });
    return { closed };
  }

  // --- Yükleme ve iş takibi ------------------------------------------------

  function upload(file, language) {
    return new Promise((resolve, reject) => {
      const data = new FormData();
      data.append("file", file);
      data.append("language", language);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/jobs");
      xhr.setRequestHeader("X-Requested-With", "fetch");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) setProgress((e.loaded / e.total) * UPLOAD_SHARE);
      };
      xhr.onload = () => {
        let body = {};
        try { body = JSON.parse(xhr.responseText); } catch {}
        if (xhr.status === 201) resolve(body);
        else reject(new Error(body.error || "Yükleme başarısız."));
      };
      xhr.onerror = () => reject(new Error("Sunucuya ulaşılamadı."));
      xhr.send(data);
    });
  }

  async function startJob(id) {
    for (let i = 0; ; i++) {
      try {
        return await api(`/api/jobs/${id}/start`, { method: "POST" });
      } catch (e) {
        if (e.status !== 403 || i >= 2) throw e;
        await sleep(1500); // saat farkı olursa kısa bekleyip tekrar dene
      }
    }
  }

  async function poll(id) {
    for (;;) {
      let job;
      try {
        job = await api(`/api/jobs/${id}`);
      } catch (e) {
        if (e.status === 404) throw new Error("İş bulunamadı veya süresi doldu.");
        await sleep(2000); // geçici ağ hatası: tekrar dene
        continue;
      }
      setProgress(UPLOAD_SHARE + (job.progress * (100 - UPLOAD_SHARE)) / 100);
      if (job.state === "done") return job;
      if (job.state === "error") throw new Error(job.error || "İşlem başarısız.");
      await sleep(1000);
    }
  }

  function resultUrl(id, format, download) {
    return `/api/jobs/${id}/result?format=${format}` + (download ? "&download=1" : "");
  }

  async function finish(id, job, autoDownload) {
    if (job.needs_end_ad) await (await showAd(id)).closed;
    const text = (await api(resultUrl(id, "txt"))).trim();
    $("text").value = text;
    $("text").placeholder = text ? "" : "Dosyada konuşma bulunamadı.";
    $("dlTxt").href = resultUrl(id, "txt", true);
    $("dlSrt").href = resultUrl(id, "srt", true);
    $("dlVtt").href = resultUrl(id, "vtt", true);
    show("result");
    if (autoDownload) $("dlTxt").click();
  }

  async function follow(id, autoDownload) {
    setJobName(id);
    show("progress");
    const job = await poll(id);
    setProgress(100);
    await finish(id, job, autoDownload);
  }

  async function start() {
    showError("");
    const file = fileInput.files[0];
    if (!file) return showError("Önce bir dosya seçin.");
    if (file.size > MAX_MB * 1024 * 1024) return showError(`Dosya en fazla ${MAX_MB} MB olabilir.`);

    $("startBtn").disabled = true;
    setProgress(0);
    try {
      // Reklam oynarken dosya arka planda yüklenir
      const ad = await showAd("start");
      const [, job] = await Promise.all([ad.closed, upload(file, $("language").value)]);
      store.set(job.id);
      await startJob(job.id);
      await follow(job.id, true);
    } catch (e) {
      if (closeAd) closeAd();
      store.clear();
      show("form");
      showError(e.message);
    } finally {
      $("startBtn").disabled = false;
    }
  }

  // Sayfa yenilendiyse devam eden işe tekrar bağlan
  async function resume() {
    const id = store.get();
    if (!id) return;
    try {
      const job = await api(`/api/jobs/${id}`);
      if (job.state === "queued" || job.state === "running" || job.state === "done") {
        await follow(id, false);
      } else {
        store.clear();
      }
    } catch (e) {
      store.clear();
      show("form");
      if (e.status !== 404) showError(e.message);
    }
  }

  // --- Olaylar -------------------------------------------------------------

  fileInput.addEventListener("change", () => {
    $("fileName").textContent = fileInput.files[0]?.name || "Dosya seç veya buraya sürükle";
  });
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (e.dataTransfer.files.length) {
      fileInput.files = e.dataTransfer.files;
      fileInput.dispatchEvent(new Event("change"));
    }
  });

  $("startBtn").addEventListener("click", start);
  $("copyBtn").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("text").value);
      $("copyBtn").textContent = "Kopyalandı";
    } catch {
      $("text").select();
    }
    setTimeout(() => ($("copyBtn").textContent = "Kopyala"), 1500);
  });
  $("againBtn").addEventListener("click", () => {
    store.clear();
    fileInput.value = "";
    $("fileName").textContent = "Dosya seç veya buraya sürükle";
    setJobName("");
    showError("");
    show("form");
  });

  resume();
})();

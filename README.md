# transcripter_free
Ücretsiz Medya Transkript Aracı

[faster-whisper](https://github.com/SYSTRAN/faster-whisper) tabanlı, reklam destekli, çok basit bir transkripsiyon sitesi.

## Akış

1. Kullanıcı dosyayı seçer ve **Başla**'ya basar.
2. 30 sn'lik tam ekran reklam oynar, dosya bu sırada arka planda yüklenir.
3. Reklam kapanınca iş kuyruğa girer. İlerleme tek bir çubukta gösterilir.
4. Bitince transkript sayfada gösterilir ve `.txt` indirmesi otomatik başlar (SRT/VTT de indirilebilir).
5. İkinci ve sonraki kullanımlarda sonuç gösterilmeden önce de reklam izletilir.

İşler arka planda çalışır. Sayfa yenilense bile iş devam eder ve kaldığı yerden bağlanılır.
Her işe Docker konteynerleri gibi okunabilir bir ad verilir (`brave_turing`, `happy_darwin`).
Reklam süreleri sunucu tarafında doğrulanır, istemci atlayamaz.

## Kurulum

```bash
pip install -r requirements.txt
SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))") python app.py
```

Tarayıcıda `http://127.0.0.1:5000` adresini açın. Uygulama `waitress` ile çalışır. Model açılışta yüklenir.
**Tek süreç** olarak çalıştırın: işler ve model bellekte tutulur.

## Reklamlar

`templates/index.html` içinde `data-ad-slot` olan üç kutu var: üst banner, sonuç öncesi banner ve tam ekran reklam.
Reklam ağınızın kodunu bu kutuların içine koyun. Reklam ağının alan adlarını `AD_CSP_SOURCES`'a eklemeyi
unutmayın, yoksa tarayıcının güvenlik politikası (CSP) reklam scriptlerini engeller.

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `SECRET_KEY` | rastgele | Oturum çerezini imzalar. Canlıda mutlaka sabit bir değer verin |
| `COOKIE_SECURE` | – | HTTPS arkasında `1` yapın |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | |
| `AD_SECONDS` | `30` | Reklam süresi |
| `AD_CSP_SOURCES` | – | Reklam ağı alan adları (boşlukla ayrılmış) |
| `MAX_UPLOAD_MB` | `500` | En büyük dosya boyutu |
| `MAX_QUEUE` | `20` | Aynı anda bekleyen en fazla iş sayısı |
| `RESULT_TTL_SECONDS` | `3600` | Sonuçların bellekte tutulma süresi |
| `WHISPER_MODEL` | GPU: `turbo`, CPU: `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `WHISPER_DEVICE` | `auto` | `cpu` veya `cuda` |
| `WHISPER_COMPUTE_TYPE` | GPU: `float16`, CPU: `int8` | |
| `WHISPER_BATCH_SIZE` | GPU: `16`, CPU: `8` | Toplu mod. `0` kapatır |
| `WHISPER_BEAM_SIZE` | `5` | `1` daha hızlı, biraz daha az doğru |

Komut satırı: `python transkript.py video.mp4 tr`

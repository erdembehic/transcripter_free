# transcripter_free
Ücretsiz Medya Transkript Aracı

Video ve ses dosyalarını [Vosk](https://alphacephei.com/vosk/) ile tamamen çevrimdışı
yazıya çeviren basit bir web uygulaması. Sonuç düz metin (`.txt`) ve altyazı (`.srt`)
olarak indirilebilir.

## Kurulum

1. Python 3.9+ ve [ffmpeg](https://ffmpeg.org/download.html) kurun (`ffmpeg` ve `ffprobe` PATH'te olmalı).
2. Bağımlılıkları yükleyin:
   ```bash
   pip install -r requirements.txt
   ```
3. Modeller: Seçilen dilin küçük modeli ilk kullanımda otomatik olarak `~/.cache/vosk`
   altına indirilir. Elle kurmak isterseniz [model listesinden](https://alphacephei.com/vosk/models)
   indirip `models/` klasörüne çıkarın (ör. `models/vosk-model-small-tr-<sürüm>`).
   Daha doğru sonuç için büyük modeller de aynı klasöre konabilir.

## Kullanım

Web arayüzü:
```bash
python app.py
```
Tarayıcıda http://127.0.0.1:5000 adresini açın.

Komut satırı:
```bash
python transkript.py video.mp4 --lang tr --format srt -o video.srt
```

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `MAX_WORKERS` | `2` | Aynı anda çalışacak transkripsiyon sayısı |
| `MAX_UPLOAD_MB` | `500` | En büyük yükleme boyutu |
| `RESULT_TTL_SECONDS` | `3600` | Bitmiş sonuçların saklanma süresi |
| `MODELS_DIR` | `./models` | Yerel Vosk modellerinin klasörü |
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Sunucu adresi |
| `FLASK_DEBUG` | kapalı | `1` yapılırsa hata ayıklama modu (yalnızca geliştirmede) |

## Testler

```bash
pip install pytest
pytest
```

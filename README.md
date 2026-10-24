# transcripter_free
Ücretsiz Medya Transkript Aracı

[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CTranslate2) tabanlı, Flask arayüzlü transkripsiyon.

## Kurulum

```bash
pip install -r requirements.txt
python app.py
```

Tarayıcıda `http://127.0.0.1:5000` adresini açın. Model ilk kullanımda indirilir ve bellekte tutulur.
Çıktı `output/` klasörüne `.txt` ve `.srt` olarak yazılır.

## Ayarlar (ortam değişkenleri)

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `WHISPER_MODEL` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `WHISPER_DEVICE` | `auto` | `cpu` veya `cuda` |
| `WHISPER_COMPUTE_TYPE` | `default` | CPU'da `int8`, GPU'da `float16` önerilir |
| `WHISPER_BEAM_SIZE` | `5` | `1` daha hızlı, biraz daha az doğru |
| `WHISPER_CPU_THREADS` | `0` | 0 = otomatik |

Komut satırı: `python transkript.py video.mp4 tr`

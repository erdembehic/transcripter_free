"""Komut satırından hızlı transkripsiyon: python transkript.py <dosya> [dil]"""
import sys

from transcriber import transcribe

if len(sys.argv) < 2:
    sys.exit("Kullanım: python transkript.py <medya_dosyası> [dil, örn. tr]")

segments, info = transcribe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
print(f"Algılanan dil: {info.language} (%{info.language_probability * 100:.0f})")
print("Transkript:")
for seg in segments:
    print(seg.text.strip())

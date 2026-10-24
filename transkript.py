"""Komut satırından transkripsiyon.

Örnek: python transkript.py video.mp4 --lang tr --format srt -o video.srt
"""
import argparse
import sys

import transcriber


def main():
    parser = argparse.ArgumentParser(description="Vosk ile medya dosyasını yazıya çevir.")
    parser.add_argument("input", help="Video veya ses dosyası")
    parser.add_argument("--lang", default="tr", choices=sorted(transcriber.LANGUAGES))
    parser.add_argument("--format", default="txt", choices=["txt", "srt"])
    parser.add_argument("-o", "--output", help="Çıktı dosyası (varsayılan: ekrana yaz)")
    args = parser.parse_args()

    def show_progress(percent):
        print(f"\rİlerleme: %{percent}", end="", file=sys.stderr, flush=True)

    try:
        segments = transcriber.transcribe(args.input, args.lang, on_progress=show_progress)
    except transcriber.TranscriptionError as exc:
        print(f"\nHata: {exc}", file=sys.stderr)
        return 1
    print(file=sys.stderr)

    if args.format == "srt":
        result = transcriber.segments_to_srt(segments)
    else:
        result = transcriber.segments_to_text(segments)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())

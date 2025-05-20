import wave
import json
from vosk import Model, KaldiRecognizer

wf = wave.open("temp_audio.wav", "rb")
model = Model("vosk-model-small-tr-0.22")
rec = KaldiRecognizer(model, wf.getframerate())

text = ""

while True:
    data = wf.readframes(4000)
    if len(data) == 0:
        break
    if rec.AcceptWaveform(data):
        result = json.loads(rec.Result())
        text += result.get("text", "") + " "

print("Transkript:\n", text)

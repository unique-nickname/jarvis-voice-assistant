
import json
import sys

import numpy as np
import sounddevice as sd
from kokoro import KPipeline

SAMPLE_RATE = 24000
VOICE = "bm_lewis"
SPEED = 1.0


def send(message):
    print("JARVIS_TTS:" + json.dumps(message), flush=True)


try:
    print("Loading Kokoro...", file=sys.stderr, flush=True)
    pipeline = KPipeline(lang_code="b")

    # Warm up the selected voice and trigger any first-use downloads.
    print("Preparing Jarvis voice...", file=sys.stderr, flush=True)

    for _, _, audio in pipeline(
        "System online.",
        voice=VOICE,
        speed=SPEED,
    ):
        pass

    print("Kokoro ready.", file=sys.stderr, flush=True)
    send({"ready": True})
except Exception as exc:
    send({"ready": False, "error": str(exc)})
    sys.exit(1)


for line in sys.stdin:
    try:
        request = json.loads(line)
        text = request.get("text", "")

        if text.strip():
            chunks = pipeline(text, voice=VOICE, speed=SPEED)
            audio_chunks = [audio for _, _, audio in chunks]

            if audio_chunks:
                audio = np.concatenate(audio_chunks)
                sd.play(audio, SAMPLE_RATE)
                sd.wait()

        send({"ok": True})

    except Exception as exc:
        send({"ok": False, "error": str(exc)})

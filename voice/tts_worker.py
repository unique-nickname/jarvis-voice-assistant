
import json
import logging
import sys
import warnings

# These are known startup notices from the pinned Kokoro/PyTorch stack. Keep
# filtering narrow and local to this worker so unrelated warnings remain visible.
warnings.filterwarnings(
    "ignore",
    message="^Can't initialize NVML$",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message="^dropout option adds dropout after all but last recurrent layer.*",
    category=UserWarning,
)
warnings.filterwarnings(
    "ignore",
    message="^`torch\\.nn\\.utils\\.weight_norm` is deprecated.*",
    category=FutureWarning,
)
warnings.filterwarnings(
    "ignore",
    message="^`torch\\.jit\\.script` is deprecated.*",
    category=FutureWarning,
)

# HF_TOKEN is optional for this public model. Hide only Hub warning-level
# notices; errors and download failures remain visible to the worker protocol.
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

import numpy as np
import sounddevice as sd
from kokoro import KPipeline

SAMPLE_RATE = 24000
VOICE = "bm_lewis"
SPEED = 1.0


def send(message):
    print("JARVIS_TTS:" + json.dumps(message), flush=True)


try:
    pipeline = KPipeline(lang_code="b", repo_id="hexgrad/Kokoro-82M")

    # Warm up the selected voice and trigger any first-use downloads.
    for _, _, audio in pipeline(
        "System online.",
        voice=VOICE,
        speed=SPEED,
    ):
        pass

    send({"ready": True})
except Exception as exc:
    send({"ready": False, "error": str(exc)})
    sys.exit(1)


try:
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
except KeyboardInterrupt:
    try:
        sd.stop()
    except Exception:
        pass

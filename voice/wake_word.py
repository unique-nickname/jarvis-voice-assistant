import time
from collections import deque
from pathlib import Path

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
FRAME_SIZE = 1280
THRESHOLD = 0.2
COOLDOWN_SECONDS = 2.0
BUFFER_SECONDS = 1.0

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "wakeword"

model = Model(
    wakeword_model_paths=[str(MODEL_DIR / "jarvis.onnx")],
    melspec_onnx_model_path=str(MODEL_DIR / "melspectrogram.onnx"),
    embedding_onnx_model_path=str(MODEL_DIR / "embedding_model.onnx"),
)


def wait_for_wake_word():
    print('Listening for "Jarvis"...')

    model.reset()

    ignore_until = time.monotonic() + 1.5
    buffer_frames = int(BUFFER_SECONDS * SAMPLE_RATE / FRAME_SIZE)
    audio_buffer = deque(maxlen=buffer_frames)

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SIZE,
        channels=1,
        dtype="int16",
    ) as stream:
        while True:
            data, overflowed = stream.read(FRAME_SIZE)

            if overflowed:
                print("Warning: microphone buffer overflow.")

            frame = np.frombuffer(data, dtype=np.int16).copy()
            audio_buffer.append(frame)

            scores = model.predict(frame)
            score = max(scores.values(), default=0.0)

            if time.monotonic() < ignore_until:
                continue

            if score >= THRESHOLD:
                print(f"Wake word detected ({score:.2f}).")
                captured_audio = np.concatenate(list(audio_buffer))
                model.reset()
                return captured_audio


import json
import logging
import os
import queue
import sys
import threading
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
import torch
from kokoro import KPipeline

SAMPLE_RATE = 24000
VOICE = "bm_lewis"
SPEED = 1.0
AUDIO_QUEUE_CHUNKS = 2


def send(message):
    print("JARVIS_TTS:" + json.dumps(message), flush=True)


def _tts_configuration():
    device = os.getenv("JARVIS_TTS_DEVICE", "auto").strip().casefold()
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError("JARVIS_TTS_DEVICE must be auto, cpu, or cuda.")

    try:
        cpu_threads = int(os.getenv("JARVIS_TTS_CPU_THREADS", "2"))
    except ValueError as exc:
        raise ValueError(
            "JARVIS_TTS_CPU_THREADS must be a whole number from 1 to 32."
        ) from exc
    if not 1 <= cpu_threads <= 32:
        raise ValueError(
            "JARVIS_TTS_CPU_THREADS must be a whole number from 1 to 32."
        )

    return device, cpu_threads


def _audio_array(audio):
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1, 1)


def _speak_chunks(text):
    audio_queue = queue.Queue(maxsize=AUDIO_QUEUE_CHUNKS)
    stop_producer = threading.Event()
    finished = object()
    producer_error = []

    def enqueue(item):
        while not stop_producer.is_set():
            try:
                audio_queue.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def synthesize():
        try:
            for _, _, audio in pipeline(text, voice=VOICE, speed=SPEED):
                if audio is not None:
                    chunk = _audio_array(audio)
                    if chunk.size and not enqueue(chunk):
                        return
        except Exception as exc:
            producer_error.append(exc)
        finally:
            enqueue(finished)

    producer = threading.Thread(
        target=synthesize,
        name="jarvis-tts-synthesis",
        daemon=True,
    )
    producer.start()

    try:
        with sd.OutputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
        ) as stream:
            while True:
                chunk = audio_queue.get()
                if chunk is finished:
                    break
                stream.write(chunk)
    finally:
        stop_producer.set()
        producer.join()

    if producer_error:
        raise producer_error[0]


try:
    configured_device, cpu_threads = _tts_configuration()
    if configured_device == "cpu" or (
        configured_device == "auto" and not torch.cuda.is_available()
    ):
        torch.set_num_threads(cpu_threads)

    pipeline = KPipeline(
        lang_code="b",
        repo_id="hexgrad/Kokoro-82M",
        device=None if configured_device == "auto" else configured_device,
    )
    selected_device = str(pipeline.model.device)

    # Warm up the selected voice and trigger any first-use downloads.
    for _, _, audio in pipeline(
        "System online.",
        voice=VOICE,
        speed=SPEED,
    ):
        pass

    send({"ready": True, "device": selected_device})
except Exception as exc:
    send({"ready": False, "error": str(exc)})
    sys.exit(1)


try:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            text = request.get("text", "")

            if text.strip():
                _speak_chunks(text)

            send({"ok": True})

        except Exception as exc:
            send({"ok": False, "error": str(exc)})
except KeyboardInterrupt:
    try:
        sd.stop()
    except Exception:
        pass

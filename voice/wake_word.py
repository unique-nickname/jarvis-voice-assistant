import json
import os
import shutil
import subprocess
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import sounddevice as sd
from openwakeword.model import Model

SAMPLE_RATE = 16000
FRAME_SIZE = 1280
DEFAULT_THRESHOLD_PERCENT = 20
COOLDOWN_SECONDS = 2.0
BUFFER_SECONDS = 1.0
INPUT_DEVICE_ENV = "WAKE_WORD_INPUT_DEVICE"
THRESHOLD_PERCENT_ENV = "WAKE_WORD_THRESHOLD_PERCENT"

MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "wakeword"

model = Model(
    wakeword_model_paths=[str(MODEL_DIR / "jarvis.onnx")],
    melspec_onnx_model_path=str(MODEL_DIR / "melspectrogram.onnx"),
    embedding_onnx_model_path=str(MODEL_DIR / "embedding_model.onnx"),
)


def _wake_word_threshold() -> float:
    raw_value = os.getenv(
        THRESHOLD_PERCENT_ENV,
        str(DEFAULT_THRESHOLD_PERCENT),
    ).strip()
    try:
        threshold_percent = int(raw_value)
    except ValueError as exc:
        raise ValueError(
            f"{THRESHOLD_PERCENT_ENV} must be a whole number from 1 to 100."
        ) from exc
    if not 1 <= threshold_percent <= 100:
        raise ValueError(f"{THRESHOLD_PERCENT_ENV} must be from 1 to 100.")
    return threshold_percent / 100


def _device_identity(device_index: int) -> tuple[str, str] | None:
    try:
        device = sd.query_devices(device_index)
        if int(device.get("max_input_channels", 0)) <= 0:
            return None
        host_api = sd.query_hostapis(device["hostapi"])
    except (sd.PortAudioError, OSError, ValueError, IndexError, TypeError):
        return None
    return str(device["name"]), str(host_api["name"])


def _wake_word_input() -> tuple[str, int | str | None]:
    """Resolve the configured microphone to PortAudio or PulseAudio capture."""
    raw_value = os.getenv(INPUT_DEVICE_ENV, "").strip()
    if not raw_value:
        return "portaudio", None

    try:
        identity = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{INPUT_DEVICE_ENV} is invalid; choose a microphone in Jarvis Settings."
        ) from exc
    if not isinstance(identity, dict):
        raise ValueError(
            f"{INPUT_DEVICE_ENV} is invalid; choose a microphone in Jarvis Settings."
        )
    backend = identity.get("backend", "portaudio")
    if backend == "pulse":
        source = identity.get("source")
        if (
            not isinstance(source, str)
            or not source.strip()
            or len(source) > 512
            or any(character in source for character in "\0\r\n")
        ):
            raise ValueError(
                f"{INPUT_DEVICE_ENV} is invalid; choose a microphone in Jarvis Settings."
            )
        return "pulse", source
    if backend != "portaudio":
        raise ValueError(
            f"{INPUT_DEVICE_ENV} has an unsupported audio capture backend."
        )

    name = identity.get("name")
    host_api = identity.get("host_api")
    saved_index = identity.get("index")
    if (
        not isinstance(name, str)
        or not isinstance(host_api, str)
        or not isinstance(saved_index, int)
        or isinstance(saved_index, bool)
        or saved_index < 0
    ):
        raise ValueError(
            f"{INPUT_DEVICE_ENV} is invalid; choose a microphone in Jarvis Settings."
        )

    if _device_identity(saved_index) == (name, host_api):
        return "portaudio", saved_index

    try:
        devices = sd.query_devices()
    except (sd.PortAudioError, OSError) as exc:
        raise RuntimeError("Could not list audio input devices.") from exc
    for device_index, device in enumerate(devices):
        if int(device.get("max_input_channels", 0)) <= 0:
            continue
        if _device_identity(device_index) == (name, host_api):
            return "portaudio", device_index

    raise RuntimeError(
        f'The configured wake-word microphone "{name}" ({host_api}) is not '
        "available. Connect it or choose another microphone in Jarvis Settings."
    )


def _default_input_sample_rate(device: int | None) -> float:
    """Get the selected input's native rate for devices that reject 16 kHz."""
    try:
        info = sd.query_devices(device, kind="input")
        sample_rate = float(info["default_samplerate"])
    except (sd.PortAudioError, OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            "Could not determine a usable sample rate for the wake-word microphone."
        ) from exc
    if sample_rate <= 0:
        raise RuntimeError(
            "The wake-word microphone did not report a usable sample rate."
        )
    return sample_rate


def _resample_frame(frame: np.ndarray, source_rate: int) -> np.ndarray:
    """Resample one short input block to the frame size expected by openWakeWord."""
    if source_rate == SAMPLE_RATE:
        return frame
    source_positions = np.arange(len(frame), dtype=np.float64)
    target_positions = np.linspace(0, len(frame) - 1, FRAME_SIZE)
    resampled = np.interp(
        target_positions,
        source_positions,
        frame.astype(np.float32),
    )
    return np.clip(np.rint(resampled), -32768, 32767).astype(np.int16)


@contextmanager
def _pulse_source_process(source: str):
    executable = shutil.which("parec")
    if executable is None:
        raise RuntimeError(
            "PipeWire/PulseAudio microphone capture needs the parec command."
        )
    command = [
        executable,
        f"--device={source}",
        "--format=s16le",
        f"--rate={SAMPLE_RATE}",
        "--channels=1",
        "--raw",
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as exc:
        raise RuntimeError("Could not start PipeWire/PulseAudio microphone capture.") from exc

    try:
        yield process
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if process.stdout is not None:
            process.stdout.close()


@contextmanager
def _wake_word_audio_reader(backend: str, selection: int | str | None):
    if backend == "pulse":
        with _pulse_source_process(str(selection)) as process:
            def read_frame() -> tuple[np.ndarray, bool]:
                if process.stdout is None:
                    raise RuntimeError("PulseAudio microphone stream is unavailable.")
                audio_bytes = process.stdout.read(FRAME_SIZE * 2)
                if len(audio_bytes) != FRAME_SIZE * 2:
                    raise RuntimeError(
                        "PipeWire/PulseAudio microphone capture stopped "
                        f"unexpectedly (parec exit code {process.poll()})."
                    )
                return np.frombuffer(audio_bytes, dtype=np.int16).copy(), False

            yield read_frame
        return

    if backend != "portaudio":
        raise ValueError("Unsupported wake-word audio capture backend.")
    device = selection if isinstance(selection, int) else None

    input_sample_rate = SAMPLE_RATE
    input_frame_size = FRAME_SIZE
    try:
        sd.check_input_settings(
            device=device,
            samplerate=input_sample_rate,
            channels=1,
            dtype="int16",
        )
    except sd.PortAudioError:
        input_sample_rate = _default_input_sample_rate(device)
        input_frame_size = max(
            1,
            round(input_sample_rate * FRAME_SIZE / SAMPLE_RATE),
        )
        print(
            "Wake-word microphone does not support 16 kHz directly; "
            f"capturing at {input_sample_rate:g} Hz and resampling."
        )

    stream_options = {
        "samplerate": input_sample_rate,
        "blocksize": input_frame_size,
        "channels": 1,
        "dtype": "int16",
        "device": device,
    }
    try:
        stream = sd.RawInputStream(**stream_options)
    except sd.PortAudioError:
        if input_sample_rate != SAMPLE_RATE:
            raise
        input_sample_rate = _default_input_sample_rate(device)
        if input_sample_rate == SAMPLE_RATE:
            raise
        input_frame_size = max(
            1,
            round(input_sample_rate * FRAME_SIZE / SAMPLE_RATE),
        )
        stream_options["samplerate"] = input_sample_rate
        stream_options["blocksize"] = input_frame_size
        print(
            "Wake-word microphone rejected 16 kHz; "
            f"capturing at {input_sample_rate:g} Hz and resampling."
        )
        stream = sd.RawInputStream(**stream_options)

    with stream:
        def read_frame() -> tuple[np.ndarray, bool]:
            data, overflowed = stream.read(input_frame_size)
            input_frame = np.frombuffer(data, dtype=np.int16).copy()
            frame = _resample_frame(
                input_frame,
                int(round(input_sample_rate)),
            )
            return frame, overflowed

        yield read_frame


def wait_for_wake_word():
    print('Listening for "Jarvis"...')

    model.reset()
    threshold = _wake_word_threshold()
    input_backend, input_selection = _wake_word_input()

    ignore_until = time.monotonic() + 1.5
    buffer_frames = int(BUFFER_SECONDS * SAMPLE_RATE / FRAME_SIZE)
    audio_buffer = deque(maxlen=buffer_frames)

    with _wake_word_audio_reader(input_backend, input_selection) as read_frame:
        while True:
            frame, overflowed = read_frame()

            if overflowed:
                print("Warning: microphone buffer overflow.")

            audio_buffer.append(frame)

            scores = model.predict(frame)
            score = max(scores.values(), default=0.0)

            if time.monotonic() < ignore_until:
                continue

            if score >= threshold:
                print(f"Wake word detected ({score:.2f}).")
                captured_audio = np.concatenate(list(audio_buffer))
                model.reset()
                return captured_audio

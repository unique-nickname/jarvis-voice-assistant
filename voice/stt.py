import collections

import sounddevice as sd
import numpy as np
import webrtcvad
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

MIN_RMS_VOLUME = 200
MIN_SPEECH_FRAMES = 1

MODEL_SIZE = "base"

print("Loading Whisper model...")
model = WhisperModel(
    MODEL_SIZE,
    device="cpu",
    compute_type="int8",
)
vad = webrtcvad.Vad(2)
print("Whisper model ready.")


def record_audio(
    silence_seconds: float = 1.2,
    max_seconds: float = 20.0,
    startup_seconds: float = 8.0,
    initial_audio: np.ndarray | None = None,
) -> np.ndarray:
    """Record speech, optionally continuing from buffered audio."""
    frames = []
    trailing_silence = collections.deque()
    pending_speech = collections.deque()

    silence_frames = int(silence_seconds * 1000 / FRAME_MS)
    max_frames = int(max_seconds * 1000 / FRAME_MS)
    startup_frames = int(startup_seconds * 1000 / FRAME_MS)

    # Buffered audio is already captured, so don't wait for speech again.
    if initial_audio is not None and initial_audio.size > 0:
        buffered = np.asarray(initial_audio, dtype=np.int16)
        frames.append(buffered.tobytes())
        started = True
        print("Continuing from buffered audio.")
    else:
        started = False

    speech_run = 0

    if not started:
        print("Listening... speak now.")

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        blocksize=FRAME_SAMPLES,
        channels=1,
        dtype="int16",
    ) as stream:
        for frame_index in range(max_frames):
            data, overflowed = stream.read(FRAME_SAMPLES)

            if overflowed:
                print("Warning: microphone buffer overflow.")

            frame = bytes(data)
            audio = np.frombuffer(frame, dtype=np.int16)

            rms = np.sqrt(np.mean(audio.astype(np.float32) ** 2))
            loud_enough = rms >= MIN_RMS_VOLUME
            is_speech = vad.is_speech(frame, SAMPLE_RATE)
            valid_speech = loud_enough and is_speech

            if not started:
                pending_speech.append((frame, valid_speech))

                while len(pending_speech) > MIN_SPEECH_FRAMES:
                    pending_speech.popleft()

                if valid_speech:
                    speech_run += 1
                else:
                    speech_run = 0

                if speech_run >= MIN_SPEECH_FRAMES:
                    started = True
                    frames.extend(f for f, _ in pending_speech)
                    pending_speech.clear()
                    print("Speech detected.")

                elif frame_index + 1 >= startup_frames:
                    print("No speech detected.")
                    break

                continue

            frames.append(frame)

            if is_speech:
                trailing_silence.clear()
            else:
                trailing_silence.append(frame)

            if len(trailing_silence) >= silence_frames:
                frames = frames[:-len(trailing_silence)]
                print("Speech finished.")
                break

    if not frames:
        return np.array([], dtype=np.float32)

    audio_bytes = b"".join(frames)
    audio = np.frombuffer(audio_bytes, dtype=np.int16)

    return audio.astype(np.float32) / 32768.0


def transcribe(audio: np.ndarray) -> str:
    """Convert recorded audio into text."""
    if audio.size == 0:
        return ""

    segments, _ = model.transcribe(
        audio,
        language="en",
        vad_filter=True,
        initial_prompt=(
            "Jarvis is a voice assistant. "
            "Common voice commands include: "
            "clip that, save a clip, open an application, "
            "control volume, pause music, resume music."
        ),
        beam_size=5,
    )

    return " ".join(
        segment.text.strip() for segment in segments
    ).strip()
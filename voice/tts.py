
import json
import subprocess
import threading
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
PYTHON = PROJECT_DIR / ".venv-kokoro" / "bin" / "python"

_worker = None
_lock = threading.Lock()


def _read_response():
    while True:
        line = _worker.stdout.readline()

        if not line:
            raise RuntimeError("Kokoro worker stopped unexpectedly.")

        if line.startswith("JARVIS_TTS:"):
            return json.loads(line[len("JARVIS_TTS:"):])


def initialize():
    global _worker

    with _lock:
        if _worker is not None and _worker.poll() is None:
            return

        _worker = subprocess.Popen(
            [str(PYTHON), "-u", "-m", "voice.tts_worker"],
            cwd=PROJECT_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
        )

        result = _read_response()

        if not result.get("ready"):
            _worker.terminate()
            _worker = None
            raise RuntimeError(
                f"Could not initialize Kokoro: {result.get('error')}"
            )


def speak(text: str) -> bool:
    """Speak text and report whether playback completed successfully."""
    if not text.strip():
        return False

    try:
        initialize()

        with _lock:
            _worker.stdin.write(json.dumps({"text": text}) + "\n")
            _worker.stdin.flush()

            result = _read_response()

            if not result.get("ok"):
                print(f"[TTS error] {result.get('error')}")
                return False

            return True

    except (OSError, RuntimeError, ValueError, BrokenPipeError) as exc:
        print(f"[TTS error] {exc}")
        return False


def shutdown():
    global _worker

    with _lock:
        if _worker is not None:
            if _worker.poll() is None:
                _worker.stdin.close()

                try:
                    _worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _worker.terminate()
                    _worker.wait()

            _worker = None

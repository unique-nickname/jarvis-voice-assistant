
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON = PROJECT_DIR / ".venv-kokoro" / "bin" / "python"

_worker = None
_lock = threading.Lock()


def _kokoro_python() -> Path:
    """Resolve the worker interpreter independently of the launch directory."""
    configured = os.environ.get("JARVIS_KOKORO_PYTHON")
    if not configured:
        candidate = DEFAULT_PYTHON
    else:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            if os.sep in configured or (os.altsep and os.altsep in configured):
                candidate = PROJECT_DIR / candidate
            else:
                resolved_executable = shutil.which(configured)
                candidate = (
                    Path(resolved_executable)
                    if resolved_executable is not None
                    else PROJECT_DIR / candidate
                )

    try:
        candidate = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RuntimeError(
            "Kokoro's Python interpreter is unavailable. Set "
            "JARVIS_KOKORO_PYTHON or run setup.sh."
        ) from exc
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeError(
            "Kokoro's Python interpreter is not executable. Set "
            "JARVIS_KOKORO_PYTHON or run setup.sh."
        )
    return candidate


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

        python_executable = _kokoro_python()
        _worker = subprocess.Popen(
            [str(python_executable), "-u", "-m", "voice.tts_worker"],
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

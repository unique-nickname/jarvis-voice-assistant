import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

_active_recorder = None

def get_active_recorder():
    """Return the recorder manager used by the current process."""
    return _active_recorder

class ClipRecorder:
    """Manage the GPU Screen Recorder replay buffer."""

    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.log_handle = None
        self.owns_process = False

        self.monitor = os.getenv("CLIP_MONITOR", "DP-1")
        self.duration = int(os.getenv("CLIP_DURATION", "60"))
        self.fps = int(os.getenv("CLIP_FPS", "60"))
        self.quality = os.getenv("CLIP_QUALITY", "very_high")
        self.codec = os.getenv("CLIP_CODEC", "h264")
        self.container = os.getenv("CLIP_FORMAT", "mp4")
        self.audio = os.getenv(
            "CLIP_AUDIO",
            "default_output|default_input",
        )

        self.output_dir = Path(
            os.path.expandvars(
                os.path.expanduser(
                    os.getenv("CLIP_DIRECTORY", "~/Videos/Clips")
                )
            )
        )

        self.log_path = (
            Path.home()
            / ".local"
            / "state"
            / "jarvis"
            / "gpu-screen-recorder.log"
        )

        global _active_recorder
        _active_recorder = self

    @staticmethod
    def _find_recorder_pids() -> list[int]:
        """Find existing GPU Screen Recorder processes."""

        pids = []

        try:
            entries = os.scandir("/proc")
        except OSError:
            return pids

        with entries:
            for entry in entries:
                if not entry.name.isdigit():
                    continue

                try:
                    with open(
                        f"/proc/{entry.name}/cmdline", "rb"
                    ) as process_file:
                        argv = process_file.read().split(b"\0")

                    if not argv or not argv[0]:
                        continue

                    executable = os.path.basename(
                        os.fsdecode(argv[0])
                    )

                    if executable == "gpu-screen-recorder":
                        pids.append(int(entry.name))

                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue

        return pids

    def start(self) -> bool:
        """Start the replay buffer without duplicating an existing recorder."""

        if self.process is not None and self.process.poll() is None:
            return True

        if self.process is not None:
            self.process = None
            self.owns_process = False

        existing = self._find_recorder_pids()

        if existing:
            print(
                "GPU Screen Recorder is already running. "
                "Leaving the existing process untouched."
            )
            return True

        executable = shutil.which("gpu-screen-recorder")

        if executable is None:
            print(
                "Clipping unavailable: gpu-screen-recorder "
                "was not found in PATH."
            )
            return False

        if self.duration < 1 or self.fps < 1:
            print("Clipping unavailable: duration and FPS must be positive.")
            return False

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

            self.log_handle = open(self.log_path, "a", buffering=1)

            command = [
                executable,
                "-w", self.monitor,
                "-c", self.container,
                "-f", str(self.fps),
                "-r", str(self.duration),
                "-a", self.audio,
                "-k", self.codec,
                "-q", self.quality,
                "-o", str(self.output_dir),
            ]

            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

            time.sleep(1.5)

            if self.process.poll() is not None:
                self.process = None
                self.log_handle.close()
                self.log_handle = None

                print(
                    "GPU Screen Recorder exited during startup. "
                    f"Check its log: {self.log_path}"
                )
                return False

            self.owns_process = True

            print(
                f"Replay buffer started: {self.duration}s, "
                f"{self.fps} FPS, monitor {self.monitor}."
            )
            return True

        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            print(f"Could not start replay buffer: {exc}")

            if self.log_handle is not None:
                self.log_handle.close()
                self.log_handle = None

            self.process = None
            self.owns_process = False
            return False

    def is_running(self) -> bool:
        """Check whether a recorder process is available."""

        if self.process is not None:
            if self.process.poll() is None:
                return True

            self.process = None
            self.owns_process = False

        return bool(self._find_recorder_pids())


    def save(self) -> dict:
        """Save the current replay buffer."""

        if self.process is not None:
            if self.process.poll() is None:
                try:
                    self.process.send_signal(signal.SIGUSR1)
                    return {
                        "success": True,
                        "action": "save",
                        "message": "Replay save requested.",
                    }
                except OSError as exc:
                    return {
                        "success": False,
                        "error": f"Could not signal recorder: {exc}",
                    }

        # Fallback for a recorder started outside this manager.
        pids = self._find_recorder_pids()

        if len(pids) != 1:
            return {
                "success": False,
                "error": (
                    "Expected exactly one running recorder, "
                    f"but found {len(pids)}."
                ),
            }

        try:
            os.kill(pids[0], signal.SIGUSR1)
            return {
                "success": True,
                "action": "save",
                "message": "Replay save requested.",
            }
        except OSError as exc:
            return {
                "success": False,
                "error": f"Could not signal recorder: {exc}",
            }


    def stop(self) -> None:
        """Stop only a recorder process started by this instance."""

        if not self.owns_process or self.process is None:
            return

        process = self.process

        try:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)

                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()

                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

            print("GPU Screen Recorder stopped.")

        except OSError as exc:
            print(f"Error stopping GPU Screen Recorder: {exc}")

        finally:
            self.process = None
            self.owns_process = False

            if self.log_handle is not None:
                self.log_handle.close()
                self.log_handle = None

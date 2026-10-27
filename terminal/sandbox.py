"""Run classified terminal commands in a constrained Bubblewrap sandbox."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


_BWRAP = Path("/usr/bin/bwrap")
_PRLIMIT = "/usr/bin/prlimit"
_MAX_ARGUMENTS = 16
_MAX_ARGUMENT_BYTES = 2_048
_DEFAULT_TIMEOUT_SECONDS = 5.0
_MAX_TIMEOUT_SECONDS = 30.0
_MAX_OUTPUT_BYTES = 8_192
_MAX_COMMAND_TMP_BYTES = 67_108_864
_MAX_PROCESSES = 32
_MAX_COMMAND_FILE_BYTES = 268_435_456
_MAX_ADDRESS_SPACE_BYTES = 268_435_456
_VISIBLE_SYSTEM_ROOTS = (
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/lib"),
    Path("/lib64"),
    Path("/etc"),
    Path("/opt"),
    Path("/var"),
)
_OUTER_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
}
_SECRET_DIRECTORY_NAMES = frozenset(
    {
        ".aws",
        ".cache",
        ".docker",
        ".gnupg",
        ".kube",
        ".mozilla",
        ".password-store",
        ".ssh",
        "bravesoftware",
        "keepass",
        "signal",
        "telegram desktop",
        "bitwarden",
        "chromium",
        "discord",
        "google-chrome",
        "keyrings",
        "microsoft-edge",
        "opera",
        "vesktop",
        "zen",
    }
)
_SECRET_DIRECTORY_SUFFIXES = (
    (".config", "gcloud"),
    (".config", "gh"),
    (".config", "rclone"),
    (".local", "share", "keyrings"),
)
_SECRET_FILENAMES = frozenset(
    {
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pgpass",
        ".pypirc",
        "application_default_credentials.json",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "secrets.json",
        "token",
        "token.json",
    }
)
_SECRET_FILE_SUFFIXES = (".key", ".pem", ".p12", ".pfx")
_SECRET_SCAN_LIMIT = 2_048


class SandboxError(RuntimeError):
    """Raised when the sandbox refuses or cannot bound a command."""


@dataclass(frozen=True, slots=True)
class SandboxCommandResult:
    returncode: int
    stdout: str
    stderr: str


class BubblewrapExecutor:
    """Execute direct read-only argv or reviewed Fish commands in Bubblewrap.

    Recognized read-only commands use direct argv without a shell. All other
    commands use Fish; the terminal service owns their approval routing.
    Bubblewrap setup failures fail closed with no host fallback.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        protected_paths: Sequence[str | Path] = (),
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("Sandbox timeout must be between 0 and 30 seconds.")
        self._timeout_seconds = float(timeout_seconds)
        self._protected_paths = tuple(
            Path(path).expanduser() for path in protected_paths
        )

    def run_read_only_argv(
        self,
        argv: Sequence[str],
        *,
        access_root: str | Path,
        working_directory: str | Path,
    ) -> SandboxCommandResult:
        """Run one already-classified Tier 1 argv without invoking a shell."""
        root, cwd = self._validate_command_scope(access_root, working_directory)
        command_argv = self._validate_argv(argv)
        executable = Path(command_argv[0])
        if not executable.is_absolute():
            executable = Path("/usr/bin", command_argv[0])
        try:
            executable = executable.resolve(strict=True)
        except OSError as exc:
            raise SandboxError("Read-only command executable is unavailable.") from exc
        if executable.parent != Path("/usr/bin") or not os.access(executable, os.X_OK):
            raise SandboxError("Read-only command executable is outside the system path.")
        process_argv = (str(executable), *command_argv[1:])
        return self._run_bwrap(
            self._build_sandbox_command(
                process_argv,
                root=root,
                cwd=cwd,
                writable=False,
                timeout_seconds=self._timeout_seconds,
                protected_paths=self._protected_paths,
            )
        )

    def run_fish_command(
        self,
        command: str,
        *,
        access_root: str | Path,
        working_directory: str | Path,
        writable: bool,
        network_access: bool = False,
    ) -> SandboxCommandResult:
        """Run a Fish command inside a rootless sandbox scoped to one tree."""
        root, cwd = self._validate_command_scope(access_root, working_directory)
        if not isinstance(command, str) or not command.strip() or "\x00" in command:
            raise SandboxError("Fish command is invalid.")
        if len(command.encode("utf-8")) > 4_096:
            raise SandboxError("Fish command exceeds the size limit.")
        if type(writable) is not bool:
            raise SandboxError("Sandbox write mode is invalid.")
        if type(network_access) is not bool:
            raise SandboxError("Sandbox network mode is invalid.")
        fish = Path("/usr/bin/fish")
        if not fish.is_file() or not os.access(fish, os.X_OK):
            raise SandboxError("Fish is unavailable; command denied.")
        return self._run_bwrap(
            self._build_sandbox_command(
                (str(fish), "--no-config", "--command", command),
                root=root,
                cwd=cwd,
                writable=writable,
                network_access=network_access,
                timeout_seconds=self._timeout_seconds,
                protected_paths=self._protected_paths,
            )
        )

    def _run_bwrap(self, command: list[str]) -> SandboxCommandResult:
        if not _BWRAP.is_file() or not os.access(_BWRAP, os.X_OK):
            raise SandboxError("Bubblewrap is unavailable; command denied.")
        if not Path(_PRLIMIT).is_file() or not os.access(_PRLIMIT, os.X_OK):
            raise SandboxError("The process-limit helper is unavailable; command denied.")
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            shell=False,
            cwd="/",
            env=dict(_OUTER_ENVIRONMENT),
            start_new_session=True,
            bufsize=0,
        )
        try:
            stdout, stderr = self._collect_output(process)
        except BaseException:
            self._kill_process(process)
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

        returncode = process.wait()
        return SandboxCommandResult(
            returncode=returncode,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    @staticmethod
    def _validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
        if isinstance(argv, (str, bytes)) or not isinstance(argv, Sequence):
            raise SandboxError("Command argv must be a sequence of strings.")
        if not argv or len(argv) > _MAX_ARGUMENTS:
            raise SandboxError("Command argv has an invalid argument count.")
        detached = tuple(argv)
        if any(not isinstance(value, str) or "\x00" in value for value in detached):
            raise SandboxError("Command argv contains invalid text.")
        if sum(len(value.encode("utf-8")) for value in detached) > _MAX_ARGUMENT_BYTES:
            raise SandboxError("Command argv exceeds the size limit.")
        return detached

    @staticmethod
    def _validate_command_scope(
        access_root: str | Path,
        working_directory: str | Path,
    ) -> tuple[Path, Path]:
        try:
            root = Path(access_root).expanduser().resolve(strict=True)
            cwd = Path(working_directory).expanduser().resolve(strict=True)
        except (OSError, RuntimeError, TypeError) as exc:
            raise SandboxError("Command path is unavailable.") from exc
        if not root.is_dir() or not cwd.is_dir():
            raise SandboxError("Command root and working directory must be directories.")
        if root == Path("/"):
            raise SandboxError("The filesystem root cannot be a command access root.")
        if root in {
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/lib"),
            Path("/lib64"),
            Path("/etc"),
            Path("/proc"),
            Path("/dev"),
            Path("/run"),
            Path("/sys"),
            Path("/tmp"),
            Path("/opt"),
            Path("/var"),
        }:
            raise SandboxError("System mount points cannot be command access roots.")
        for system_root in (
            Path("/usr"),
            Path("/bin"),
            Path("/sbin"),
            Path("/lib"),
            Path("/lib64"),
            Path("/etc"),
            Path("/proc"),
            Path("/dev"),
            Path("/run"),
            Path("/sys"),
            Path("/opt"),
            Path("/var"),
        ):
            if root.is_relative_to(system_root):
                raise SandboxError("System paths cannot be command access roots.")
        try:
            cwd.relative_to(root)
        except ValueError as exc:
            raise SandboxError("Working directory is outside the allowed root.") from exc
        return root, cwd

    @classmethod
    def _build_sandbox_command(
        cls,
        process_argv: Sequence[str],
        *,
        root: Path,
        cwd: Path,
        writable: bool,
        network_access: bool = False,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        protected_paths: Sequence[str | Path] = (),
    ) -> list[str]:
        cpu_seconds = max(1, int(timeout_seconds) - 1)
        bwrap_command = [
            str(_BWRAP),
            "--die-with-parent",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-ipc",
            "--disable-userns",
            "--assert-userns-disabled",
            "--uid",
            "0",
            "--gid",
            "0",
            "--cap-drop",
            "ALL",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind-try",
            "/bin",
            "/bin",
            "--ro-bind-try",
            "/sbin",
            "/sbin",
            "--ro-bind-try",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            "--ro-bind",
            "/etc",
            "/etc",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            str(_MAX_COMMAND_TMP_BYTES),
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/run",
            "--tmpfs",
            "/sys",
        ]
        if not network_access:
            bwrap_command.insert(5, "--unshare-net")

        for optional_root in (Path("/opt"), Path("/var")):
            if optional_root.is_dir():
                bwrap_command.extend(
                    ["--ro-bind-try", str(optional_root), str(optional_root)]
                )

        for parent in reversed(root.parents[:-1]):
            if parent == Path("/"):
                continue
            if parent in {
                Path("/usr"),
                Path("/bin"),
                Path("/sbin"),
                Path("/lib"),
                Path("/lib64"),
                Path("/etc"),
                Path("/proc"),
                Path("/dev"),
                Path("/tmp"),
                Path("/run"),
                Path("/sys"),
                Path("/opt"),
                Path("/var"),
            }:
                continue
            bwrap_command.extend(["--dir", str(parent)])
        bwrap_command.extend(
            [
                "--dir",
                str(root),
                "--ro-bind" if not writable else "--bind",
                str(root),
                str(root),
            ]
        )
        bwrap_command.extend(
            cls._secret_mask_arguments(root, protected_paths=protected_paths)
        )

        bwrap_command.extend(
            [
                "--clearenv",
                "--setenv",
                "PATH",
                "/usr/bin:/bin:/usr/local/bin:/usr/sbin:/sbin",
                "--setenv",
                "HOME",
                str(root),
                "--setenv",
                "LANG",
                "C",
                "--setenv",
                "LC_ALL",
                "C",
                "--chdir",
                str(cwd),
                "--",
                _PRLIMIT,
                f"--nproc={_MAX_PROCESSES}:{_MAX_PROCESSES}",
                f"--cpu={cpu_seconds}:{cpu_seconds + 1}",
                f"--fsize={_MAX_COMMAND_FILE_BYTES}:{_MAX_COMMAND_FILE_BYTES}",
                "--nofile=64:64",
                f"--as={_MAX_ADDRESS_SPACE_BYTES}:{_MAX_ADDRESS_SPACE_BYTES}",
                "--",
                *process_argv,
            ]
        )
        return bwrap_command

    @staticmethod
    def _secret_mask_arguments(
        root: Path,
        *,
        protected_paths: Sequence[str | Path] = (),
    ) -> list[str]:
        protected_directories: list[Path] = []
        protected_files: list[Path] = []
        count = 0

        for protected_path in protected_paths:
            try:
                candidate = Path(protected_path).expanduser().resolve(strict=True)
            except FileNotFoundError:
                continue
            except (OSError, RuntimeError, TypeError) as exc:
                raise SandboxError(
                    "A protected application path is unavailable."
                ) from exc

            if candidate == root:
                raise SandboxError(
                    "The terminal root cannot be a protected application path."
                )
            try:
                candidate.relative_to(root)
            except ValueError:
                continue

            if candidate.is_dir():
                protected_directories.append(candidate)
            elif candidate.is_file():
                protected_files.append(candidate)
            else:
                raise SandboxError(
                    "A protected application path is not a regular file or directory."
                )

        for current_root, directory_names, file_names in os.walk(
            root,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_root)
            retained_directories: list[str] = []
            for name in directory_names:
                candidate = current / name
                relative_parts = candidate.relative_to(root).parts
                is_secret = (
                    name.casefold() in _SECRET_DIRECTORY_NAMES
                    or any(
                        tuple(part.casefold() for part in relative_parts[-len(suffix):])
                        == suffix
                        for suffix in _SECRET_DIRECTORY_SUFFIXES
                        if len(relative_parts) >= len(suffix)
                    )
                )
                if is_secret:
                    if candidate.is_symlink():
                        count += BubblewrapExecutor._protect_symlink_target(
                            candidate,
                            root,
                            protected_directories,
                            protected_files,
                        )
                    else:
                        protected_directories.append(candidate)
                        count += 1
                else:
                    retained_directories.append(name)
            directory_names[:] = retained_directories

            for name in file_names:
                lowered = name.casefold()
                if (
                    (lowered.startswith(".env") and lowered != ".env.example")
                    or lowered in _SECRET_FILENAMES
                    or lowered.endswith(_SECRET_FILE_SUFFIXES)
                    or any(
                        marker in lowered
                        for marker in ("credential", "secret", "token")
                    )
                    or (current.name == ".git" and lowered == "config")
                ):
                    candidate = current / name
                    if candidate.is_symlink():
                        count += BubblewrapExecutor._protect_symlink_target(
                            candidate,
                            root,
                            protected_directories,
                            protected_files,
                        )
                    elif candidate.is_file():
                        protected_files.append(candidate)
                        count += 1
            if count > _SECRET_SCAN_LIMIT:
                raise SandboxError("Too many protected paths to prepare safely.")

        # A parent tmpfs already hides every protected path beneath it. Avoid
        # generating nested mounts, which Bubblewrap may reject.
        unique_directories = sorted(
            set(protected_directories),
            key=lambda item: (len(item.parts), str(item)),
        )
        visible_directories: list[Path] = []
        for directory in unique_directories:
            if not any(
                directory.is_relative_to(parent)
                for parent in visible_directories
            ):
                visible_directories.append(directory)

        visible_files = sorted(
            (
                file_path
                for file_path in set(protected_files)
                if not any(
                    file_path.is_relative_to(directory)
                    for directory in visible_directories
                )
            ),
            key=str,
        )

        arguments: list[str] = []
        for directory in visible_directories:
            arguments.extend(["--tmpfs", str(directory)])
        for file_path in visible_files:
            arguments.extend(["--ro-bind", "/dev/null", str(file_path)])
        return arguments

    @staticmethod
    def _protect_symlink_target(
        candidate: Path,
        root: Path,
        protected_directories: list[Path],
        protected_files: list[Path],
    ) -> int:
        """Mask a sensitive symlink's target if that target is sandbox-visible.

        Symlink targets outside the access root are visible only when they fall
        under one of the system trees explicitly mounted by the sandbox. Other
        external targets are inaccessible there, so they need no masking.
        Broken links and loops also expose no target contents.
        """
        try:
            target = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            return 0

        if not target.is_relative_to(root) and not any(
            target.is_relative_to(system_root)
            for system_root in _VISIBLE_SYSTEM_ROOTS
        ):
            return 0

        if target.is_dir():
            protected_directories.append(target)
        elif target.is_file():
            protected_files.append(target)
        else:
            raise SandboxError(
                "A protected symlink target is not a regular file or directory."
            )
        return 1

    def _collect_output(
        self,
        process: subprocess.Popen[bytes],
    ) -> tuple[bytes, bytes]:
        if process.stdout is None or process.stderr is None:
            raise SandboxError("Could not capture sandbox output.")

        selector = selectors.DefaultSelector()
        output = {"stdout": bytearray(), "stderr": bytearray()}
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)

        deadline = time.monotonic() + self._timeout_seconds
        termination_deadline: float | None = None
        total_bytes = 0
        exceeded_output = False
        timed_out = False
        try:
            while selector.get_map() or process.poll() is None:
                now = time.monotonic()
                if termination_deadline is None and now >= deadline:
                    timed_out = True
                    self._kill_process(process)
                    termination_deadline = now + 0.5
                if termination_deadline is not None and now >= termination_deadline:
                    break

                wait_for = (
                    min(0.1, max(0.0, deadline - now))
                    if termination_deadline is None
                    else min(0.1, max(0.0, termination_deadline - now))
                )
                if not selector.get_map():
                    try:
                        process.wait(timeout=wait_for)
                    except subprocess.TimeoutExpired:
                        pass
                    continue
                for key, _ in selector.select(wait_for):
                    try:
                        chunk = os.read(key.fd, 4_096)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue

                    remaining = _MAX_OUTPUT_BYTES - total_bytes
                    if len(chunk) > remaining:
                        if not exceeded_output:
                            exceeded_output = True
                            self._kill_process(process)
                            if termination_deadline is None:
                                termination_deadline = time.monotonic() + 0.5
                        continue
                    if not exceeded_output:
                        output[key.data].extend(chunk)
                        total_bytes += len(chunk)
            if timed_out:
                raise SandboxError("Sandbox command exceeded its time limit.")
            if exceeded_output:
                raise SandboxError("Sandbox command exceeded its output limit.")
        finally:
            selector.close()

        return bytes(output["stdout"]), bytes(output["stderr"])

    @staticmethod
    def _kill_process(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass

"""Run a tiny allowlist of commands in a constrained Bubblewrap sandbox."""

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
_ALLOWED_EXECUTABLES = frozenset({"/usr/bin/uname"})
_MAX_ARGUMENTS = 16
_MAX_ARGUMENT_BYTES = 2_048
_DEFAULT_TIMEOUT_SECONDS = 5.0
_MAX_OUTPUT_BYTES = 8_192
_MAX_TMP_BYTES = 1_048_576
_MAX_PROCESSES = 32
_MAX_CPU_SECONDS = 4
_MAX_ADDRESS_SPACE_BYTES = 268_435_456
_OUTER_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C",
    "LC_ALL": "C",
}


class SandboxError(RuntimeError):
    """Raised when the sandbox refuses or cannot bound a command."""


@dataclass(frozen=True, slots=True)
class SandboxCommandResult:
    returncode: int
    stdout: str
    stderr: str


class BubblewrapExecutor:
    """Execute trusted fixed-argv commands with isolated host access.

    There is no shell, caller-provided environment, or caller-provided working
    directory. The executable allowlist is deliberately narrow. Bubblewrap
    setup failures fail closed; commands never fall back to host execution.
    """

    def __init__(self, *, timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= _DEFAULT_TIMEOUT_SECONDS
        ):
            raise ValueError("Sandbox timeout must be between 0 and 5 seconds.")
        self._timeout_seconds = float(timeout_seconds)

    def run(
        self,
        executable: str,
        arguments: Sequence[str] = (),
    ) -> SandboxCommandResult:
        """Run one allowlisted executable and return bounded UTF-8 output."""
        command_arguments = self._validate_command(executable, arguments)
        if not _BWRAP.is_file() or not os.access(_BWRAP, os.X_OK):
            raise SandboxError("Bubblewrap is unavailable; command denied.")
        if not Path(_PRLIMIT).is_file() or not os.access(_PRLIMIT, os.X_OK):
            raise SandboxError("The process-limit helper is unavailable; command denied.")

        process = subprocess.Popen(
            self._build_command(executable, command_arguments),
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
    def _validate_command(
        executable: str,
        arguments: Sequence[str],
    ) -> tuple[str, ...]:
        if (
            not isinstance(executable, str)
            or executable not in _ALLOWED_EXECUTABLES
        ):
            raise SandboxError("Executable is not allowlisted.")
        if isinstance(arguments, (str, bytes)) or not isinstance(arguments, Sequence):
            raise SandboxError("Command arguments must be a sequence of strings.")
        if len(arguments) > _MAX_ARGUMENTS:
            raise SandboxError("Too many command arguments.")
        detached_arguments = tuple(arguments)
        if any(
            not isinstance(argument, str) or "\x00" in argument
            for argument in detached_arguments
        ):
            raise SandboxError("Command arguments are invalid.")
        argument_bytes = sum(
            len(argument.encode("utf-8")) for argument in detached_arguments
        )
        if argument_bytes > _MAX_ARGUMENT_BYTES:
            raise SandboxError("Command arguments exceed the size limit.")
        return detached_arguments

    @staticmethod
    def _build_command(executable: str, arguments: tuple[str, ...]) -> list[str]:
        command = [
            str(_BWRAP),
            "--die-with-parent",
            "--unshare-user",
            "--unshare-pid",
            "--unshare-net",
            "--unshare-uts",
            "--unshare-ipc",
            "--disable-userns",
            "--assert-userns-disabled",
            "--uid",
            "65534",
            "--gid",
            "65534",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind-try",
            "/bin",
            "/bin",
            "--ro-bind-try",
            "/lib",
            "/lib",
            "--ro-bind-try",
            "/lib64",
            "/lib64",
            "--dir",
            "/etc",
            "--ro-bind-try",
            "/etc/ld.so.cache",
            "/etc/ld.so.cache",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--size",
            str(_MAX_TMP_BYTES),
            "--tmpfs",
            "/tmp",
            "--clearenv",
            "--setenv",
            "PATH",
            "/usr/bin:/bin",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "LANG",
            "C",
            "--setenv",
            "LC_ALL",
            "C",
            "--chdir",
            "/tmp",
            "--",
            _PRLIMIT,
            f"--nproc={_MAX_PROCESSES}:{_MAX_PROCESSES}",
            f"--cpu={_MAX_CPU_SECONDS}:{_MAX_CPU_SECONDS + 1}",
            "--fsize=0:0",
            "--nofile=64:64",
            f"--as={_MAX_ADDRESS_SPACE_BYTES}:{_MAX_ADDRESS_SPACE_BYTES}",
            "--",
            executable,
        ]
        command.extend(arguments)
        return command

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

"""Unit tests for sandbox command construction and fixed diagnostics."""

from __future__ import annotations

import os
import subprocess
import threading
import unittest
from unittest.mock import Mock, patch

from terminal import OperationRegistry, TerminalPolicyError
from terminal.operations import kernel_info_operation
from terminal.sandbox import BubblewrapExecutor, SandboxCommandResult, SandboxError


class TerminalSandboxTests(unittest.TestCase):
    def test_command_builder_sets_isolation_and_resource_limits(self) -> None:
        command = BubblewrapExecutor._build_command("/usr/bin/uname", ("-sr",))

        self.assertEqual(command[0], "/usr/bin/bwrap")
        for required_flag in (
            "--unshare-user",
            "--unshare-pid",
            "--unshare-net",
            "--disable-userns",
            "--assert-userns-disabled",
            "--clearenv",
            "--tmpfs",
            "--proc",
            "--dev",
        ):
            self.assertIn(required_flag, command)
        self.assertIn("65534", command)
        self.assertIn("--nproc=32:32", command)
        self.assertIn("--fsize=0:0", command)
        self.assertEqual(command[-2:], ["/usr/bin/uname", "-sr"])

    def test_executor_rejects_non_allowlisted_executable_before_launch(self) -> None:
        executor = BubblewrapExecutor()
        with patch("terminal.sandbox.subprocess.Popen") as popen:
            with self.assertRaisesRegex(SandboxError, "not allowlisted"):
                executor.run("/bin/sh", ("-c", "id"))
        popen.assert_not_called()

    def test_executor_rejects_invalid_or_oversized_arguments(self) -> None:
        executor = BubblewrapExecutor()
        with self.assertRaisesRegex(SandboxError, "invalid"):
            executor.run("/usr/bin/uname", ("bad\x00argument",))
        with self.assertRaisesRegex(SandboxError, "Too many"):
            executor.run("/usr/bin/uname", tuple("x" for _ in range(17)))
        with self.assertRaisesRegex(SandboxError, "size limit"):
            executor.run("/usr/bin/uname", ("x" * 2_049,))

    def test_executor_rejects_unbounded_timeouts(self) -> None:
        for timeout in (0, 5.1, float("inf"), True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    BubblewrapExecutor(timeout_seconds=timeout)

    def test_output_capture_stops_at_the_combined_limit(self) -> None:
        class FinishedProcess:
            pid = 2_000_000_000

            def __init__(self) -> None:
                stdout_read, self.stdout_write_fd = os.pipe()
                stderr_read, stderr_write = os.pipe()
                os.close(stderr_write)
                self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
                self.stderr = os.fdopen(stderr_read, "rb", buffering=0)

            def poll(self) -> int:
                return 0

            def wait(self, timeout: float | None = None) -> int:
                return 0

            def kill(self) -> None:
                return None

        process = FinishedProcess()

        def write_output() -> None:
            try:
                os.write(process.stdout_write_fd, b"x" * 8_193)
            finally:
                os.close(process.stdout_write_fd)

        writer = threading.Thread(target=write_output)
        writer.start()
        try:
            with patch(
                "terminal.sandbox.os.killpg",
                side_effect=ProcessLookupError,
            ):
                with self.assertRaisesRegex(SandboxError, "output limit"):
                    BubblewrapExecutor()._collect_output(process)
        finally:
            writer.join(timeout=1)
            process.stdout.close()
            process.stderr.close()

    def test_output_capture_kills_a_process_at_the_deadline(self) -> None:
        class RunningProcess:
            pid = 2_000_000_001

            def __init__(self) -> None:
                stdout_read, self.stdout_write_fd = os.pipe()
                stderr_read, self.stderr_write_fd = os.pipe()
                self.stdout = os.fdopen(stdout_read, "rb", buffering=0)
                self.stderr = os.fdopen(stderr_read, "rb", buffering=0)

            def poll(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                raise subprocess.TimeoutExpired("sandbox", timeout)

            def kill(self) -> None:
                return None

        process = RunningProcess()
        try:
            with (
                patch(
                    "terminal.sandbox.time.monotonic",
                    side_effect=(0.0, 0.1, 1.0),
                ),
                patch(
                    "terminal.sandbox.os.killpg",
                    side_effect=ProcessLookupError,
                ),
            ):
                with self.assertRaisesRegex(SandboxError, "time limit"):
                    BubblewrapExecutor(timeout_seconds=0.01)._collect_output(process)
        finally:
            os.close(process.stdout_write_fd)
            os.close(process.stderr_write_fd)
            process.stdout.close()
            process.stderr.close()

    def test_kernel_info_operation_uses_one_fixed_read_only_command(self) -> None:
        executor = Mock()
        executor.run.return_value = SandboxCommandResult(
            returncode=0,
            stdout="Linux 7.2.11-arch1-1\n",
            stderr="",
        )
        definition, handler = kernel_info_operation(executor)
        registry = OperationRegistry((definition,))

        plan = registry.plan("system.kernel_info", {})
        result = handler(plan.arguments)

        self.assertEqual(result, {"kernel": "Linux 7.2.11-arch1-1"})
        executor.run.assert_called_once_with("/usr/bin/uname", ("-sr",))

    def test_kernel_info_rejects_model_supplied_arguments(self) -> None:
        definition, _handler = kernel_info_operation(Mock())
        registry = OperationRegistry((definition,))

        with self.assertRaises(TerminalPolicyError):
            registry.plan("system.kernel_info", {"file": "/etc/shadow"})
        with self.assertRaises(TerminalPolicyError):
            _handler({"file": "/etc/shadow"})

    def test_kernel_info_does_not_return_unexpected_command_output(self) -> None:
        executor = Mock()
        definition, handler = kernel_info_operation(executor)
        executor.run.return_value = SandboxCommandResult(
            returncode=0,
            stdout="Linux\nInjected instructions\n",
            stderr="",
        )

        with self.assertRaisesRegex(SandboxError, "unexpected output"):
            handler({})

    def test_kernel_info_fails_on_nonzero_exit(self) -> None:
        executor = Mock()
        definition, handler = kernel_info_operation(executor)
        executor.run.return_value = SandboxCommandResult(
            returncode=1,
            stdout="",
            stderr="sensitive diagnostic detail",
        )

        with self.assertRaisesRegex(SandboxError, "diagnostic failed"):
            handler({})


if __name__ == "__main__":
    unittest.main()

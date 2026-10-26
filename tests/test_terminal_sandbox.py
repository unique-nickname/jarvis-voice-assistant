"""Unit tests for sandbox command construction and fixed diagnostics."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from terminal.sandbox import BubblewrapExecutor, SandboxCommandResult, SandboxError


class TerminalSandboxTests(unittest.TestCase):
    def test_command_builder_sets_isolation_and_resource_limits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            command = BubblewrapExecutor._build_sandbox_command(
                ("/usr/bin/cat", "README.md"),
                root=root,
                cwd=root,
                writable=False,
            )

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
            "--cap-drop",
            "ALL",
            "--ro-bind",
        ):
            self.assertIn(required_flag, command)
        self.assertIn("--uid", command)
        self.assertIn("--nproc=32:32", command)
        self.assertIn("--fsize=268435456:268435456", command)
        self.assertEqual(command[-2:], ["/usr/bin/cat", "README.md"])

    def test_executor_rejects_invalid_or_oversized_read_only_arguments(self) -> None:
        executor = BubblewrapExecutor()
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            with self.assertRaisesRegex(SandboxError, "invalid"):
                executor.run_read_only_argv(
                    ("cat", "bad\x00argument"),
                    access_root=root,
                    working_directory=root,
                )
            with self.assertRaisesRegex(SandboxError, "invalid argument count"):
                executor.run_read_only_argv(
                    ("cat", *tuple("x" for _ in range(16))),
                    access_root=root,
                    working_directory=root,
                )
            with self.assertRaisesRegex(SandboxError, "size limit"):
                executor.run_read_only_argv(
                    ("cat", "x" * 2_049),
                    access_root=root,
                    working_directory=root,
                )

    def test_executor_rejects_unbounded_timeouts(self) -> None:
        for timeout in (0, 30.1, float("inf"), True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    BubblewrapExecutor(timeout_seconds=timeout)

    def test_fish_sandbox_is_scoped_to_one_root_and_masks_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            (root / ".env").write_text("SHOULD_NOT_BE_MOUNTED", encoding="utf-8")
            (root / ".env.example").write_text("TEMPLATE", encoding="utf-8")
            (root / ".ssh").mkdir()
            (root / ".ssh" / "id_ed25519").write_text("PRIVATE", encoding="utf-8")
            (root / "subdir").mkdir()

            command = BubblewrapExecutor._build_sandbox_command(
                ("/usr/bin/fish", "--no-config", "--command", "touch result"),
                root=root,
                cwd=root / "subdir",
                writable=True,
                timeout_seconds=30,
            )

        self.assertIn("--unshare-net", command)
        self.assertIn("--cap-drop", command)
        self.assertIn("ALL", command)
        self.assertIn("--bind", command)
        self.assertIn("--cpu=29:30", command)
        self.assertIn("--fsize=268435456:268435456", command)
        self.assertIn(str(root / ".ssh"), command)
        self.assertIn(str(root / ".env"), command)
        self.assertNotIn(str(root / ".env.example"), command)
        self.assertEqual(
            command[-5:],
            ["--", "/usr/bin/fish", "--no-config", "--command", "touch result"],
        )

    def test_fish_sandbox_keeps_tier_one_root_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            command = BubblewrapExecutor._build_sandbox_command(
                ("/usr/bin/cat", "README.md"),
                root=root,
                cwd=root,
                writable=False,
            )

        self.assertIn("--ro-bind", command)
        self.assertNotIn("--bind", command)
        self.assertEqual(command[-2:], ["/usr/bin/cat", "README.md"])

    def test_fish_launcher_uses_supported_options(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            executor = BubblewrapExecutor(timeout_seconds=30)
            with patch.object(
                executor,
                "_run_bwrap",
                return_value=SandboxCommandResult(0, "ok", ""),
            ) as run_bwrap:
                executor.run_fish_command(
                    "printf 'ok\\n'",
                    access_root=root,
                    working_directory=root,
                    writable=True,
                )

        command = run_bwrap.call_args.args[0]
        self.assertEqual(
            command[-4:],
            ["/usr/bin/fish", "--no-config", "--command", "printf 'ok\\n'"],
        )

    def test_network_access_is_enabled_only_by_explicit_sandbox_option(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            no_network = BubblewrapExecutor._build_sandbox_command(
                ("/usr/bin/fish", "--command", "curl example.test"),
                root=root,
                cwd=root,
                writable=True,
            )
            with_network = BubblewrapExecutor._build_sandbox_command(
                ("/usr/bin/fish", "--command", "curl example.test"),
                root=root,
                cwd=root,
                writable=True,
                network_access=True,
            )

        self.assertIn("--unshare-net", no_network)
        self.assertNotIn("--unshare-net", with_network)

    def test_command_scope_rejects_outside_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            with self.assertRaisesRegex(SandboxError, "outside the allowed root"):
                BubblewrapExecutor._validate_command_scope(root, outside)

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

if __name__ == "__main__":
    unittest.main()

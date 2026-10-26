"""Tests for command classification, approval routing, and execution binding."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from terminal.approval import ApprovalState
from terminal.command_service import CommandTerminalService
from terminal.policy import RiskTier
from terminal.service import ExecutionStatus
from terminal.sandbox import SandboxCommandResult


class TerminalCommandServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_root = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_root.name)
        self.executor = Mock()
        self.executor.run_read_only_argv.return_value = SandboxCommandResult(
            returncode=0,
            stdout="example output\n",
            stderr="",
        )
        self.executor.run_fish_command.return_value = SandboxCommandResult(
            returncode=0,
            stdout="approved output\n",
            stderr="",
        )
        self.reviewed_plans = []
        self.reviewer = Mock(side_effect=self.approve)
        self.service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
        )

    def tearDown(self) -> None:
        self.temporary_root.cleanup()

    def approve(self, queue, request_id: str) -> ApprovalState:
        self.reviewed_plans.append(queue.pending_ticket(request_id).plan)
        return queue.approve_from_ui(request_id).state

    def test_recognized_read_only_command_runs_without_review_or_shell(self) -> None:
        response = self.service.run_command("cat README.md")

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(response["result"]["stdout"], "example output\n")
        self.executor.run_read_only_argv.assert_called_once_with(
            ("cat", "README.md"),
            access_root=self.root,
            working_directory=str(self.root),
        )
        self.executor.run_fish_command.assert_not_called()
        self.reviewer.assert_not_called()

    def test_unrecognized_command_always_waits_for_local_approval(self) -> None:
        response = self.service.run_command("unknown_diagnostic --check")

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(response["result"]["exit_code"], 0)
        self.executor.run_fish_command.assert_called_once_with(
            "unknown_diagnostic --check",
            access_root=self.root,
            working_directory=str(self.root),
            writable=True,
            network_access=False,
        )
        self.reviewer.assert_called_once()

    def test_shell_compound_command_is_approved_as_one_exact_request(self) -> None:
        command = "cat README.md | grep example"

        response = self.service.run_command(command)

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(len(self.reviewed_plans), 1)
        self.assertEqual(self.reviewed_plans[0].arguments["command"], command)
        self.assertIn(str(self.root), self.reviewed_plans[0].preview.affected_resources[1])
        self.executor.run_fish_command.assert_called_once_with(
            command,
            access_root=self.root,
            working_directory=str(self.root),
            writable=True,
            network_access=False,
        )

    def test_network_request_moves_a_read_only_command_to_tier_two(self) -> None:
        response = self.service.run_command("cat README.md", network_access=True)

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(len(self.reviewed_plans), 1)
        self.assertTrue(self.reviewed_plans[0].arguments["network_access"])
        self.assertIn(
            "Network access: enabled",
            self.reviewed_plans[0].preview.affected_resources[2],
        )
        self.executor.run_read_only_argv.assert_not_called()
        self.executor.run_fish_command.assert_called_once_with(
            "cat README.md",
            access_root=self.root,
            working_directory=str(self.root),
            writable=True,
            network_access=True,
        )

    def test_tier_three_command_is_denied_without_prompt_or_execution(self) -> None:
        response = self.service.run_command("sudo pacman -S fish")

        self.assertEqual(response["status"], ExecutionStatus.DENIED.value)
        self.assertEqual(response["detail"], "tier_3_denied_by_default")
        self.reviewer.assert_not_called()
        self.executor.run_fish_command.assert_not_called()
        self.executor.run_read_only_argv.assert_not_called()

    def test_tier_two_mapped_to_tier_one_runs_without_approval(self) -> None:
        service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
            tier_overrides={RiskTier.MODIFICATION: RiskTier.READ_ONLY},
        )

        response = service.run_command("touch test.txt")

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(response["result"]["source_tier"], 2)
        self.assertEqual(response["result"]["effective_tier"], 1)
        self.assertEqual(response["result"]["access_root"], str(self.root))
        self.assertEqual(response["result"]["sandbox_home"], str(self.root))
        self.executor.run_fish_command.assert_called_once_with(
            "touch test.txt",
            access_root=self.root,
            working_directory=str(self.root),
            writable=True,
            network_access=False,
        )
        self.reviewer.assert_not_called()

    def test_tier_two_mapped_to_tier_three_is_denied(self) -> None:
        service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
            tier_overrides={RiskTier.MODIFICATION: RiskTier.HIGH_RISK},
        )

        response = service.run_command("touch test.txt")

        self.assertEqual(response["status"], ExecutionStatus.DENIED.value)
        self.reviewer.assert_not_called()
        self.executor.run_fish_command.assert_not_called()
        self.executor.run_read_only_argv.assert_not_called()

    def test_tier_three_mapped_to_tier_two_requires_approval(self) -> None:
        service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
            tier_overrides={RiskTier.HIGH_RISK: RiskTier.MODIFICATION},
        )

        response = service.run_command("sudo id")

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(len(self.reviewed_plans), 1)
        self.assertEqual(self.reviewed_plans[0].arguments["source_tier"], 3)
        self.assertEqual(self.reviewed_plans[0].arguments["effective_tier"], 2)
        self.executor.run_fish_command.assert_called_once()

    def test_tier_three_mapped_to_tier_one_runs_without_approval(self) -> None:
        service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
            tier_overrides={RiskTier.HIGH_RISK: RiskTier.READ_ONLY},
        )

        response = service.run_command("rm test.txt")

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(response["result"]["source_tier"], 3)
        self.assertEqual(response["result"]["effective_tier"], 1)
        self.executor.run_fish_command.assert_called_once()
        self.reviewer.assert_not_called()

    def test_tier_one_mapped_to_tier_two_requires_approval(self) -> None:
        service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
            tier_overrides={RiskTier.READ_ONLY: RiskTier.MODIFICATION},
        )

        response = service.run_command("cat README.md")

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(len(self.reviewed_plans), 1)
        self.assertEqual(self.reviewed_plans[0].arguments["source_tier"], 1)
        self.assertEqual(self.reviewed_plans[0].arguments["effective_tier"], 2)
        self.executor.run_read_only_argv.assert_not_called()
        self.executor.run_fish_command.assert_called_once()

    def test_tier_one_mapped_to_tier_three_is_denied(self) -> None:
        service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
            tier_overrides={RiskTier.READ_ONLY: RiskTier.HIGH_RISK},
        )

        response = service.run_command("cat README.md")

        self.assertEqual(response["status"], ExecutionStatus.DENIED.value)
        self.reviewer.assert_not_called()
        self.executor.run_read_only_argv.assert_not_called()
        self.executor.run_fish_command.assert_not_called()

    def test_network_access_cannot_be_downgraded_to_tier_one(self) -> None:
        service = CommandTerminalService(
            self.root,
            executor=self.executor,
            reviewer=self.reviewer,
            tier_overrides={RiskTier.MODIFICATION: RiskTier.READ_ONLY},
        )

        response = service.run_command("cat README.md", network_access=True)

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.assertEqual(len(self.reviewed_plans), 1)
        self.assertEqual(self.reviewed_plans[0].arguments["effective_tier"], 2)
        self.assertTrue(self.reviewed_plans[0].arguments["network_access"])

    def test_nonzero_command_exit_is_reported_as_failed(self) -> None:
        self.executor.run_read_only_argv.return_value = SandboxCommandResult(
            returncode=1,
            stdout="",
            stderr="missing file\n",
        )

        response = self.service.run_command("cat missing.txt")

        self.assertEqual(response["status"], ExecutionStatus.FAILED.value)
        self.assertEqual(response["detail"], "command_exit_nonzero")
        self.assertEqual(response["result"]["stderr"], "missing file\n")
        self.reviewer.assert_not_called()

    def test_working_directory_must_stay_within_access_root(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            response = self.service.run_command("cat README.md", outside)

        self.assertEqual(response["status"], ExecutionStatus.FAILED.value)
        self.executor.run_read_only_argv.assert_not_called()
        self.executor.run_fish_command.assert_not_called()

    def test_relative_working_directory_resolves_inside_root(self) -> None:
        subdirectory = self.root / "subdir"
        subdirectory.mkdir()

        response = self.service.run_command("cat README.md", "subdir")

        self.assertEqual(response["status"], ExecutionStatus.COMPLETED.value)
        self.executor.run_read_only_argv.assert_called_once_with(
            ("cat", "README.md"),
            access_root=self.root,
            working_directory=str(subdirectory),
        )


if __name__ == "__main__":
    unittest.main()

"""Tests for automatic risk assignment of assistant-generated commands."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from terminal.command_policy import (
    MAX_COMMAND_CHARS,
    assess_command,
    tier_overrides_from_environment,
)
from terminal.policy import RiskTier, TerminalPolicyError


class TerminalCommandPolicyTests(unittest.TestCase):
    def test_tier_overrides_default_to_identity_mapping(self) -> None:
        overrides = tier_overrides_from_environment({})

        self.assertEqual(
            overrides,
            {
                RiskTier.READ_ONLY: RiskTier.READ_ONLY,
                RiskTier.MODIFICATION: RiskTier.MODIFICATION,
                RiskTier.HIGH_RISK: RiskTier.HIGH_RISK,
            },
        )

    def test_tier_overrides_allow_any_valid_target_tier(self) -> None:
        overrides = tier_overrides_from_environment(
            {
                "TERMINAL_TIER_1_OVERRIDE": "3",
                "TERMINAL_TIER_2_OVERRIDE": "1",
                "TERMINAL_TIER_3_OVERRIDE": "2",
            }
        )

        self.assertEqual(
            overrides,
            {
                RiskTier.READ_ONLY: RiskTier.HIGH_RISK,
                RiskTier.MODIFICATION: RiskTier.READ_ONLY,
                RiskTier.HIGH_RISK: RiskTier.MODIFICATION,
            },
        )

    def test_invalid_tier_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be 1, 2, or 3"):
            tier_overrides_from_environment({"TERMINAL_TIER_2_OVERRIDE": "0"})

    def test_known_read_only_command_is_tier_one_with_direct_argv(self) -> None:
        with patch(
            "terminal.command_policy.shutil_which",
            return_value="/usr/bin/cat",
        ):
            assessment = assess_command("cat README.md")

        self.assertEqual(assessment.risk_tier, RiskTier.READ_ONLY)
        self.assertEqual(assessment.argv, ("cat", "README.md"))

    def test_unrecognized_command_is_tier_two_even_when_not_installed(self) -> None:
        assessment = assess_command("jarvis_unknown_diagnostic --check")

        self.assertEqual(assessment.risk_tier, RiskTier.MODIFICATION)
        self.assertEqual(
            assessment.reason,
            "unrecognized_or_mutating_command_requires_approval",
        )
        self.assertIsNone(assessment.argv)

    def test_known_mutating_command_is_tier_two(self) -> None:
        assessment = assess_command("touch report.txt")

        self.assertEqual(assessment.risk_tier, RiskTier.MODIFICATION)

    def test_tier_three_escalation_and_destructive_commands_are_denied(self) -> None:
        for command in (
            "sudo pacman -S fish",
            "env sudo id",
            "command rm report.txt",
            "rm report.txt",
            "chmod 777 config.ini",
            "mount /dev/sda1 /mnt",
            "cat report.txt | rm report.txt",
            "cat report.txt\nrm report.txt",
            "find . -delete",
            "find . -exec rm report.txt \\;",
            "echo $(sudo id)",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    assess_command(command).risk_tier,
                    RiskTier.HIGH_RISK,
                )

    def test_shell_syntax_requires_tier_two_approval(self) -> None:
        for command in (
            "cat README.md | grep Jarvis",
            "cat README.md > copy.txt",
            "echo $(whoami)",
        ):
            with self.subTest(command=command):
                assessment = assess_command(command)
                self.assertEqual(assessment.risk_tier, RiskTier.MODIFICATION)
                self.assertEqual(assessment.reason, "shell_syntax_requires_approval")

    def test_a_high_risk_word_in_an_argument_is_not_a_tier_three_command(self) -> None:
        assessment = assess_command("echo rm")

        self.assertEqual(assessment.risk_tier, RiskTier.MODIFICATION)

    def test_commands_outside_the_fixed_path_are_not_tier_one(self) -> None:
        with patch(
            "terminal.command_policy.shutil_which",
            return_value="/home/user/bin/cat",
        ):
            assessment = assess_command("cat README.md")

        self.assertEqual(assessment.risk_tier, RiskTier.MODIFICATION)

    def test_empty_oversized_and_nul_commands_are_rejected(self) -> None:
        for command in ("", "  ", "cat\x00README", "x" * (MAX_COMMAND_CHARS + 1)):
            with self.subTest(command=command[:20]):
                with self.assertRaises(TerminalPolicyError):
                    assess_command(command)


if __name__ == "__main__":
    unittest.main()

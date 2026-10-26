"""Tests for opt-in terminal service construction."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from terminal.command_service import CommandTerminalService
from terminal.operations import create_terminal_service
from terminal.policy import RiskTier


class TerminalOperationsTests(unittest.TestCase):
    def test_terminal_service_is_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(create_terminal_service())

    def test_enabled_service_uses_configured_access_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            with patch.dict(
                os.environ,
                {
                    "TERMINAL_COMMANDS_ENABLED": "true",
                    "TERMINAL_WRITE_ROOT": temporary_root,
                },
                clear=True,
            ):
                service = create_terminal_service()

        self.assertIsInstance(service, CommandTerminalService)
        self.assertEqual(service.access_root, Path(temporary_root))

    def test_enabled_service_reads_tier_override_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            with patch.dict(
                os.environ,
                {
                    "TERMINAL_COMMANDS_ENABLED": "true",
                    "TERMINAL_WRITE_ROOT": temporary_root,
                    "TERMINAL_TIER_1_OVERRIDE": "3",
                    "TERMINAL_TIER_2_OVERRIDE": "1",
                    "TERMINAL_TIER_3_OVERRIDE": "2",
                },
                clear=True,
            ):
                service = create_terminal_service()

        self.assertEqual(service.tier_overrides[RiskTier.READ_ONLY], RiskTier.HIGH_RISK)
        self.assertEqual(service.tier_overrides[RiskTier.MODIFICATION], RiskTier.READ_ONLY)
        self.assertEqual(service.tier_overrides[RiskTier.HIGH_RISK], RiskTier.MODIFICATION)

    def test_invalid_tier_override_prevents_terminal_service_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_root:
            with patch.dict(
                os.environ,
                {
                    "TERMINAL_COMMANDS_ENABLED": "true",
                    "TERMINAL_WRITE_ROOT": temporary_root,
                    "TERMINAL_TIER_3_OVERRIDE": "4",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(ValueError, "must be 1, 2, or 3"):
                    create_terminal_service()


if __name__ == "__main__":
    unittest.main()

"""Tests for the deliberately narrow assistant-facing terminal tool."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from tools.registry import TERMINAL_TOOLS, TOOLS, handlers_for, tools_for


class TerminalToolRegistryTests(unittest.TestCase):
    def test_terminal_tool_is_absent_without_a_service(self) -> None:
        self.assertEqual(tools_for(), TOOLS)
        self.assertNotIn("run_terminal_command", handlers_for())

    def test_service_adds_one_command_tool_with_no_model_selected_tier(self) -> None:
        service = Mock()
        schemas = tools_for(terminal_service=service)

        self.assertEqual(schemas, [*TOOLS, *TERMINAL_TOOLS])
        schema = schemas[-1]
        self.assertEqual(schema["name"], "run_terminal_command")
        self.assertEqual(
            set(schema["parameters"]["properties"]),
            {"command", "working_directory", "network_access"},
        )
        self.assertEqual(
            schema["parameters"]["required"],
            ["command", "working_directory", "network_access"],
        )
        self.assertFalse(schema["parameters"]["additionalProperties"])

    def test_bound_handler_passes_exact_command_to_service(self) -> None:
        service = Mock()
        service.run_command.return_value = {"status": "completed"}
        handler = handlers_for(terminal_service=service)["run_terminal_command"]

        result = handler("echo hello", "/tmp", False)

        self.assertEqual(result, {"status": "completed"})
        service.run_command.assert_called_once_with("echo hello", "/tmp", False)


if __name__ == "__main__":
    unittest.main()

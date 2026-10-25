"""Tests for the deliberately narrow assistant-facing terminal tool."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from tools.registry import TERMINAL_TOOLS, TOOLS, handlers_for, tools_for


class TerminalToolRegistryTests(unittest.TestCase):
    def test_terminal_tool_is_absent_without_a_service(self) -> None:
        self.assertEqual(tools_for(), TOOLS)
        self.assertNotIn("get_kernel_info", handlers_for())

    def test_service_adds_only_the_zero_argument_kernel_tool(self) -> None:
        service = Mock()
        schemas = tools_for(terminal_service=service)

        self.assertEqual(schemas, [*TOOLS, *TERMINAL_TOOLS])
        schema = schemas[-1]
        self.assertEqual(schema["name"], "get_kernel_info")
        self.assertEqual(schema["parameters"]["properties"], {})
        self.assertEqual(schema["parameters"]["required"], [])
        self.assertFalse(schema["parameters"]["additionalProperties"])

    def test_bound_handler_calls_only_kernel_info(self) -> None:
        execution = Mock()
        execution.as_dict.return_value = {
            "operation_id": "system.kernel_info",
            "status": "completed",
            "result": {"kernel": "Linux example"},
        }
        service = Mock()
        service.execute.return_value = execution
        handler = handlers_for(terminal_service=service)["get_kernel_info"]

        result = handler()

        self.assertEqual(result, execution.as_dict.return_value)
        service.execute.assert_called_once_with("system.kernel_info", {})


if __name__ == "__main__":
    unittest.main()

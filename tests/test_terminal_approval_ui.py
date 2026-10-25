"""Tests for the local approval-window adapter without opening a GUI."""

from __future__ import annotations

import io
import json
import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from terminal import (
    ApprovalQueue,
    ApprovalState,
    ChangePreview,
    OperationDefinition,
    OperationRegistry,
    RiskTier,
)
from terminal.approval_ui import (
    ApprovalWindowError,
    _request_floating,
    _should_float_window,
    review_approval,
)


def _validate(arguments: dict[str, object]) -> None:
    if set(arguments) != {"target", "label"}:
        raise ValueError("Unexpected arguments.")
    if arguments["target"] != "workspace":
        raise ValueError("Unsupported target.")


def _preview(arguments: dict[str, object]) -> ChangePreview:
    return ChangePreview(
        title="Preview a workspace change",
        description="Review the requested effect before continuing.",
        affected_resources=("workspace",),
    )


class ApprovalUiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.queue = ApprovalQueue(
            OperationRegistry(
                (
                    OperationDefinition(
                        operation_id="workspace.update",
                        risk_tier=RiskTier.MODIFICATION,
                        validate_arguments=_validate,
                        build_preview=_preview,
                    ),
                )
            ),
            clock=lambda: self.now,
        )
        self.ticket = self.queue.request(
            "workspace.update",
            {"target": "workspace", "label": "<safe> & bidi\u202e"},
        )

    @patch("terminal.approval_ui._find_zenity", return_value="/usr/bin/zenity")
    @patch("terminal.approval_ui.subprocess.run")
    @patch.dict(
        os.environ,
        {
            "DISPLAY": ":9",
            "OPENAI_API_KEY": "test-secret-must-not-reach-ui",
        },
        clear=True,
    )
    def test_approve_shows_escaped_plan_and_records_only_ui_choice(
        self,
        run_mock,
        _find_mock,
    ) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/zenity"],
            returncode=0,
            stdout="",
            stderr="",
        )

        state = review_approval(self.queue, self.ticket.request_id)

        self.assertEqual(state, ApprovalState.APPROVED)
        command = run_mock.call_args.args[0]
        options = run_mock.call_args.kwargs
        self.assertEqual(command[0], "/usr/bin/zenity")
        self.assertIn("--text-info", command)
        self.assertIn("--ok-label=Approve", command)
        self.assertIn("--cancel-label=Deny", command)
        self.assertIn("--default-cancel", command)
        self.assertIs(options["shell"], False)
        self.assertNotIn("OPENAI_API_KEY", options["env"])
        self.assertIn('"label": "<safe> & bidi\\u202e"', options["input"])
        self.assertNotIn("bidi\u202e", options["input"])

    @patch("terminal.approval_ui._find_zenity", return_value="/usr/bin/zenity")
    @patch("terminal.approval_ui.subprocess.run")
    @patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}, clear=True)
    def test_cancel_and_window_timeout_never_approve(
        self,
        run_mock,
        _find_mock,
    ) -> None:
        run_mock.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/zenity"],
            returncode=1,
            stdout="",
            stderr="",
        )
        state = review_approval(self.queue, self.ticket.request_id)
        self.assertEqual(state, ApprovalState.DENIED)

        new_ticket = self.queue.request(
            "workspace.update",
            {"target": "workspace", "label": "timeout test"},
        )
        run_mock.return_value = subprocess.CompletedProcess(
            args=["/usr/bin/zenity"],
            returncode=5,
            stdout="",
            stderr="",
        )
        state = review_approval(self.queue, new_ticket.request_id)
        self.assertEqual(state, ApprovalState.DENIED)

    @patch.dict(os.environ, {}, clear=True)
    def test_no_display_fails_closed_and_leaves_request_pending(self) -> None:
        with self.assertRaises(ApprovalWindowError):
            review_approval(self.queue, self.ticket.request_id)
        self.assertEqual(self.queue.state(self.ticket.request_id), ApprovalState.PENDING)

    @patch("terminal.approval_ui._find_zenity", return_value="/usr/bin/zenity")
    @patch(
        "terminal.approval_ui.subprocess.run",
        side_effect=OSError("simulated launch failure"),
    )
    @patch.dict(os.environ, {"DISPLAY": ":9"}, clear=True)
    def test_dialog_launch_failure_leaves_request_pending(
        self,
        _run_mock,
        _find_mock,
    ) -> None:
        with self.assertRaises(ApprovalWindowError):
            review_approval(self.queue, self.ticket.request_id)
        self.assertEqual(self.queue.state(self.ticket.request_id), ApprovalState.PENDING)

    @patch("terminal.approval_ui._find_zenity", return_value="/usr/bin/zenity")
    @patch(
        "terminal.approval_ui.subprocess.run",
        side_effect=subprocess.TimeoutExpired("zenity", 90),
    )
    @patch.dict(os.environ, {"DISPLAY": ":9"}, clear=True)
    def test_subprocess_timeout_denies_the_pending_request(
        self,
        _run_mock,
        _find_mock,
    ) -> None:
        state = review_approval(self.queue, self.ticket.request_id)
        self.assertEqual(state, ApprovalState.DENIED)

    def test_auto_floating_detects_hyprland_and_supports_overrides(self) -> None:
        with patch.dict(
            os.environ,
            {"XDG_CURRENT_DESKTOP": "GNOME:Hyprland"},
            clear=True,
        ):
            self.assertTrue(_should_float_window())

        with patch.dict(
            os.environ,
            {
                "HYPRLAND_INSTANCE_SIGNATURE": "instance",
                "TERMINAL_APPROVAL_FLOATING": "never",
            },
            clear=True,
        ):
            self.assertFalse(_should_float_window())

        with patch.dict(
            os.environ,
            {"TERMINAL_APPROVAL_FLOATING": "always"},
            clear=True,
        ):
            self.assertTrue(_should_float_window())

    def test_hyprland_floats_only_the_matching_zenity_window(self) -> None:
        process = Mock()
        process.pid = 4321
        process.stdin = io.StringIO()
        process.poll.return_value = None
        process.wait.return_value = 0
        clients = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps(
                [
                    {
                        "pid": 4321,
                        "title": "Zenity text view",
                        "initialTitle": "Jarvis: Review requested change",
                        "address": "0xabc123",
                        "floating": False,
                    },
                    {
                        "pid": 9876,
                        "title": "Another window",
                        "address": "0xdef456",
                        "floating": False,
                    },
                ]
            ),
            stderr="",
        )
        floated = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="",
            stderr="",
        )

        with (
            patch.dict(
                os.environ,
                {
                    "DISPLAY": ":9",
                    "HYPRLAND_INSTANCE_SIGNATURE": "instance",
                },
                clear=True,
            ),
            patch("terminal.approval_ui._find_zenity", return_value="/usr/bin/zenity"),
            patch("terminal.approval_ui._find_hyprctl", return_value="/usr/bin/hyprctl"),
            patch("terminal.approval_ui.subprocess.Popen", return_value=process) as popen,
            patch(
                "terminal.approval_ui.subprocess.run",
                side_effect=[clients, floated],
            ) as run,
        ):
            state = review_approval(self.queue, self.ticket.request_id)

        self.assertEqual(state, ApprovalState.APPROVED)
        launch_command = popen.call_args.args[0]
        self.assertEqual(launch_command[0], "/usr/bin/zenity")
        self.assertFalse(popen.call_args.kwargs["shell"])
        self.assertEqual(
            run.call_args_list[1].args[0],
            [
                "/usr/bin/hyprctl",
                "dispatch",
                "setfloating",
                "address:0xabc123",
            ],
        )

    def test_hyprland_lua_dispatch_is_tried_when_legacy_dispatch_fails(self) -> None:
        with (
            patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "instance"}, clear=True),
            patch(
                "terminal.approval_ui.subprocess.run",
                side_effect=(
                    subprocess.CompletedProcess(
                        args=[],
                        returncode=1,
                        stdout="",
                        stderr="unknown dispatcher",
                    ),
                    subprocess.CompletedProcess(
                        args=[],
                        returncode=0,
                        stdout="ok",
                        stderr="",
                    ),
                ),
            ) as run,
        ):
            self.assertTrue(_request_floating("/usr/bin/hyprctl", "0xabc123"))

        self.assertEqual(
            run.call_args_list[1].args[0],
            [
                "/usr/bin/hyprctl",
                "dispatch",
                'hl.dsp.window.float({ action = "set", '
                'window = hl.get_window("address:0xabc123") })',
            ],
        )


if __name__ == "__main__":
    unittest.main()

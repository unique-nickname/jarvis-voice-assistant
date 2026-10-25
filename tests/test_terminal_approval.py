"""Tests for the non-executing terminal policy and approval foundation."""

from __future__ import annotations

import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from terminal import (
    ApprovalError,
    ApprovalQueue,
    ApprovalState,
    ChangePreview,
    OperationDefinition,
    OperationRegistry,
    RiskTier,
    TerminalPolicyError,
)


def _validate_target(arguments: dict[str, object]) -> None:
    target = arguments.get("target")
    if target not in {"workspace", "user-service"}:
        raise TerminalPolicyError("Unsupported target.")


def _preview(arguments: dict[str, object]) -> ChangePreview:
    target = str(arguments["target"])
    return ChangePreview(
        title="Update an approved target",
        description=f"Apply the operation to {target}.",
        affected_resources=(target,),
    )


def _read_only_preview(arguments: dict[str, object]) -> ChangePreview:
    return ChangePreview(
        title="Read diagnostic information",
        description="Inspect the system without changing it.",
    )


def _must_not_build_tier_three_preview(arguments: dict[str, object]) -> ChangePreview:
    raise AssertionError("Tier 3 previews must not be built.")


def _must_not_validate_tier_three(arguments: dict[str, object]) -> None:
    raise AssertionError("Tier 3 arguments must not be validated for execution.")


class TerminalApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = 100.0

        def clock() -> float:
            return self.now

        self.operations = OperationRegistry(
            (
                OperationDefinition(
                    operation_id="workspace.update",
                    risk_tier=RiskTier.MODIFICATION,
                    validate_arguments=_validate_target,
                    build_preview=_preview,
                ),
                OperationDefinition(
                    operation_id="system.inspect",
                    risk_tier=RiskTier.READ_ONLY,
                    validate_arguments=lambda arguments: None,
                    build_preview=_read_only_preview,
                ),
                OperationDefinition(
                    operation_id="system.privileged-change",
                    risk_tier=RiskTier.HIGH_RISK,
                    validate_arguments=_must_not_validate_tier_three,
                    build_preview=_must_not_build_tier_three_preview,
                ),
            )
        )
        self.queue = ApprovalQueue(
            self.operations,
            ttl_seconds=30,
            clock=clock,
        )

    def test_unregistered_operations_are_denied(self) -> None:
        with self.assertRaises(TerminalPolicyError):
            self.operations.plan("fish", {"command": "echo hello"})

    def test_operation_arguments_are_validated_by_local_policy(self) -> None:
        with self.assertRaises(TerminalPolicyError):
            self.operations.plan("workspace.update", {"target": "/etc"})

    def test_tier_one_does_not_enter_approval_queue(self) -> None:
        with self.assertRaisesRegex(ApprovalError, "do not require approval"):
            self.queue.request("system.inspect", {})

    def test_tier_three_is_denied_by_default(self) -> None:
        with self.assertRaisesRegex(ApprovalError, "denied by default"):
            self.queue.request(
                "system.privileged-change",
                {"target": "user-service"},
            )

    def test_tier_two_requires_approval_and_can_be_consumed_only_once(self) -> None:
        ticket = self.queue.request(
            "workspace.update",
            {"target": "workspace"},
        )
        self.assertEqual(ticket.state, ApprovalState.PENDING)
        self.assertEqual(self.queue.pending(), (ticket,))

        approved = self.queue.approve_from_ui(ticket.request_id)
        self.assertEqual(approved.state, ApprovalState.APPROVED)
        plan = self.queue.consume_approved(ticket.request_id)
        self.assertEqual(plan.operation_id, "workspace.update")
        self.assertEqual(plan.arguments, {"target": "workspace"})
        self.assertEqual(self.queue.state(ticket.request_id), ApprovalState.CONSUMED)
        with self.assertRaisesRegex(ApprovalError, "not been approved"):
            self.queue.consume_approved(ticket.request_id)

    def test_denied_request_cannot_be_approved_or_consumed(self) -> None:
        ticket = self.queue.request(
            "workspace.update",
            {"target": "workspace"},
        )
        self.queue.deny_from_ui(ticket.request_id)
        self.assertEqual(self.queue.state(ticket.request_id), ApprovalState.DENIED)
        with self.assertRaises(ApprovalError):
            self.queue.approve_from_ui(ticket.request_id)
        with self.assertRaises(ApprovalError):
            self.queue.consume_approved(ticket.request_id)

    def test_expired_request_disappears_and_cannot_be_approved(self) -> None:
        ticket = self.queue.request(
            "workspace.update",
            {"target": "workspace"},
        )
        self.now += 30
        self.assertEqual(self.queue.pending(), ())
        self.assertEqual(self.queue.state(ticket.request_id), ApprovalState.EXPIRED)
        with self.assertRaises(ApprovalError):
            self.queue.approve_from_ui(ticket.request_id)

    def test_caller_cannot_mutate_the_arguments_in_an_existing_plan(self) -> None:
        supplied_arguments = {"target": "workspace"}
        plan = self.operations.plan("workspace.update", supplied_arguments)
        supplied_arguments["target"] = "/etc"
        returned_arguments = plan.arguments
        returned_arguments["target"] = "/root"
        self.assertEqual(plan.arguments, {"target": "workspace"})

    def test_pending_queue_has_a_fixed_capacity(self) -> None:
        for _ in range(8):
            self.queue.request("workspace.update", {"target": "workspace"})
        with self.assertRaisesRegex(ApprovalError, "Too many terminal approvals"):
            self.queue.request("workspace.update", {"target": "workspace"})

    def test_approved_request_can_only_be_consumed_once_across_threads(self) -> None:
        ticket = self.queue.request(
            "workspace.update",
            {"target": "workspace"},
        )
        self.queue.approve_from_ui(ticket.request_id)
        barrier = Barrier(2)

        def consume_once() -> bool:
            barrier.wait()
            try:
                self.queue.consume_approved(ticket.request_id)
                return True
            except ApprovalError:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(lambda _: consume_once(), range(2)))
        self.assertEqual(sum(results), 1)

    def test_preview_escapes_control_characters(self) -> None:
        preview = ChangePreview(
            title="Update\nsettings",
            description="Apply a change.",
            affected_resources=("workspace\u202e",),
        )
        self.assertEqual(preview.title, "Update\\u000asettings")
        self.assertEqual(preview.affected_resources, ("workspace\\u202e",))

    def test_arguments_must_be_strictly_json_serializable(self) -> None:
        with self.assertRaises(TerminalPolicyError):
            self.operations.plan("workspace.update", {"target": object()})
        with self.assertRaises(TerminalPolicyError):
            self.operations.plan("workspace.update", {1: "workspace"})

    def test_approval_expires_even_after_it_was_approved(self) -> None:
        ticket = self.queue.request(
            "workspace.update",
            {"target": "workspace"},
        )
        self.queue.approve_from_ui(ticket.request_id)
        self.now += 30
        with self.assertRaisesRegex(ApprovalError, "expired"):
            self.queue.consume_approved(ticket.request_id)


if __name__ == "__main__":
    unittest.main()

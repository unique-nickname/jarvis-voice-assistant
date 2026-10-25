"""In-memory approval queue for future Tier 2 operations.

The queue never executes commands. A future local UI may approve or deny a
pending request; assistant tools must not be given access to those methods.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from terminal.policy import OperationPlan, OperationRegistry, RiskTier


DEFAULT_APPROVAL_TTL_SECONDS = 90.0
MAX_PENDING_APPROVALS = 8
MAX_RECORDED_APPROVALS = 64


class ApprovalError(RuntimeError):
    """Raised when an approval request cannot be approved or consumed."""


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class ApprovalTicket:
    request_id: str
    plan: OperationPlan
    state: ApprovalState
    expires_in_seconds: float


@dataclass(slots=True)
class _ApprovalRecord:
    plan: OperationPlan
    expires_at: float
    state: ApprovalState


class ApprovalQueue:
    """Manage one-time approval for plans classified as Tier 2.

    This class does not authenticate a user. Only a future local UI should be
    allowed to call the `*_from_ui` methods; assistant tools must never expose
    them.
    """

    def __init__(
        self,
        operations: OperationRegistry,
        *,
        ttl_seconds: float = DEFAULT_APPROVAL_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not math.isfinite(ttl_seconds)
            or ttl_seconds <= 0
        ):
            raise ValueError("Approval lifetime must be positive.")
        self._operations = operations
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._requests: dict[str, _ApprovalRecord] = {}
        self._lock = threading.RLock()

    def request(
        self,
        operation_id: str,
        arguments: dict[str, object],
    ) -> ApprovalTicket:
        risk_tier = self._operations.tier_for(operation_id)
        if risk_tier is RiskTier.READ_ONLY:
            raise ApprovalError("Tier 1 operations do not require approval.")
        if risk_tier is RiskTier.HIGH_RISK:
            raise ApprovalError("Tier 3 operations are denied by default.")
        plan = self._operations.plan(operation_id, arguments)

        with self._lock:
            self._expire_due_requests()
            outstanding = sum(
                record.state in (ApprovalState.PENDING, ApprovalState.APPROVED)
                for record in self._requests.values()
            )
            if outstanding >= MAX_PENDING_APPROVALS:
                raise ApprovalError("Too many terminal approvals are outstanding.")
            self._trim_terminal_records()
            if len(self._requests) >= MAX_RECORDED_APPROVALS:
                raise ApprovalError("Terminal approval history is full.")

            request_id = secrets.token_urlsafe(24)
            record = _ApprovalRecord(
                plan=plan,
                expires_at=self._clock() + self._ttl_seconds,
                state=ApprovalState.PENDING,
            )
            self._requests[request_id] = record
            return self._ticket(request_id, record)

    def pending(self) -> tuple[ApprovalTicket, ...]:
        with self._lock:
            self._expire_due_requests()
            return tuple(
                self._ticket(request_id, record)
                for request_id, record in self._requests.items()
                if record.state is ApprovalState.PENDING
            )

    def approve_from_ui(self, request_id: str) -> ApprovalTicket:
        with self._lock:
            record = self._get_request(request_id)
            self._ensure_pending(record)
            record.state = ApprovalState.APPROVED
            return self._ticket(request_id, record)

    def deny_from_ui(self, request_id: str) -> ApprovalTicket:
        with self._lock:
            record = self._get_request(request_id)
            self._ensure_pending(record)
            record.state = ApprovalState.DENIED
            return self._ticket(request_id, record)

    def consume_approved(self, request_id: str) -> OperationPlan:
        """Return the exact approved plan once; no process is launched here."""
        with self._lock:
            record = self._get_request(request_id)
            if record.state is ApprovalState.EXPIRED:
                raise ApprovalError("Terminal approval has expired.")
            if record.state is not ApprovalState.APPROVED:
                raise ApprovalError("This terminal plan has not been approved.")
            if self._is_expired(record):
                record.state = ApprovalState.EXPIRED
                raise ApprovalError("Terminal approval has expired.")
            record.state = ApprovalState.CONSUMED
            return record.plan

    def state(self, request_id: str) -> ApprovalState:
        with self._lock:
            record = self._get_request(request_id)
            if record.state in (ApprovalState.PENDING, ApprovalState.APPROVED):
                if self._is_expired(record):
                    record.state = ApprovalState.EXPIRED
            return record.state

    def _get_request(self, request_id: str) -> _ApprovalRecord:
        try:
            record = self._requests[request_id]
        except KeyError as exc:
            raise ApprovalError("Unknown terminal approval request.") from exc
        if record.state in (ApprovalState.PENDING, ApprovalState.APPROVED):
            if self._is_expired(record):
                record.state = ApprovalState.EXPIRED
        return record

    def _ticket(self, request_id: str, record: _ApprovalRecord) -> ApprovalTicket:
        return ApprovalTicket(
            request_id=request_id,
            plan=record.plan,
            state=record.state,
            expires_in_seconds=max(0.0, record.expires_at - self._clock()),
        )

    def _ensure_pending(self, record: _ApprovalRecord) -> None:
        if record.state is not ApprovalState.PENDING:
            raise ApprovalError(f"Approval request is {record.state.value}.")

    def _expire_due_requests(self) -> None:
        for record in self._requests.values():
            if record.state in (ApprovalState.PENDING, ApprovalState.APPROVED):
                if self._is_expired(record):
                    record.state = ApprovalState.EXPIRED

    def _trim_terminal_records(self) -> None:
        if len(self._requests) < MAX_RECORDED_APPROVALS:
            return
        for request_id, record in tuple(self._requests.items()):
            if record.state not in (ApprovalState.PENDING, ApprovalState.APPROVED):
                del self._requests[request_id]
                if len(self._requests) < MAX_RECORDED_APPROVALS:
                    break

    def _is_expired(self, record: _ApprovalRecord) -> bool:
        return self._clock() >= record.expires_at

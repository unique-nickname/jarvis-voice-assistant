"""Data types and JSON validation for local Jarvis memory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any


SCHEMA_VERSION = 1


class MemoryTier(str, Enum):
    SESSION = "session"
    TEMPORARY = "temporary"
    PERMANENT = "permanent"


class MemorySource(str, Enum):
    USER = "user"
    JARVIS = "jarvis"


class MemoryError(Exception):
    """Base exception for memory service errors."""


class MemoryValidationError(MemoryError):
    """Raised when memory data is malformed or violates the schema."""


class UnsupportedSchemaVersionError(MemoryValidationError):
    """Raised when a memory file uses a schema version this code cannot read."""


class MemoryStorageError(MemoryError):
    """Raised when a memory file cannot be read or safely written."""


class MemoryConflictError(MemoryError):
    """Raised when a memory file changes during a service write."""


class MemoryEntryNotFoundError(MemoryError):
    """Raised when an update targets an unknown memory entry."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def format_timestamp(value: datetime) -> str:
    value = require_utc(value, "timestamp")
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise MemoryValidationError(f"{field_name} must be a UTC timestamp string.")

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryValidationError(
            f"{field_name} must be a valid UTC timestamp."
        ) from exc

    return require_utc(parsed, field_name)


def require_utc(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MemoryValidationError(f"{field_name} must include a timezone.")

    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise MemoryValidationError(f"{field_name} has an invalid timezone.") from exc

    if offset != timedelta(0):
        raise MemoryValidationError(f"{field_name} must use UTC.")

    return value.astimezone(timezone.utc).replace(microsecond=0)


def _require_keys(
    value: dict[str, Any],
    expected: set[str],
    description: str,
) -> None:
    actual = set(value)
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing {sorted(missing)}")
        if extra:
            details.append(f"unknown {sorted(extra)}")
        raise MemoryValidationError(
            f"{description} has invalid fields: {', '.join(details)}."
        )


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: str
    text: str
    tags: tuple[str, ...]
    source: MemorySource
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        try:
            canonical_id = str(uuid.UUID(self.id))
        except (AttributeError, TypeError, ValueError) as exc:
            raise MemoryValidationError("Memory entry id must be a UUID.") from exc
        object.__setattr__(self, "id", canonical_id)

        if not isinstance(self.text, str) or not self.text.strip():
            raise MemoryValidationError("Memory entry text must not be empty.")
        object.__setattr__(self, "text", self.text.strip())

        if isinstance(self.tags, str):
            raise MemoryValidationError("Memory entry tags must be a list of strings.")
        try:
            normalized_tags = tuple(tag.strip() for tag in self.tags)
        except (AttributeError, TypeError) as exc:
            raise MemoryValidationError(
                "Memory entry tags must be a list of strings."
            ) from exc
        if any(not tag for tag in normalized_tags):
            raise MemoryValidationError("Memory entry tags must not be empty.")
        if len(set(normalized_tags)) != len(normalized_tags):
            raise MemoryValidationError("Memory entry tags must be unique.")
        object.__setattr__(self, "tags", normalized_tags)

        try:
            source = MemorySource(self.source)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError(
                "Memory entry source must be 'user' or 'jarvis'."
            ) from exc
        object.__setattr__(self, "source", source)

        object.__setattr__(
            self, "created_at", require_utc(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", require_utc(self.updated_at, "updated_at")
        )
        if self.expires_at is not None:
            object.__setattr__(
                self, "expires_at", require_utc(self.expires_at, "expires_at")
            )

    def is_expired(self, now: datetime) -> bool:
        return self.expires_at is not None and self.expires_at <= require_utc(
            now, "now"
        )

    def to_json(self, tier: MemoryTier) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "text": self.text,
            "tags": list(self.tags),
            "source": self.source.value,
            "created_at": format_timestamp(self.created_at),
            "updated_at": format_timestamp(self.updated_at),
        }
        if tier is MemoryTier.TEMPORARY:
            if self.expires_at is None:
                raise MemoryValidationError(
                    "Temporary memory entries require expires_at."
                )
            value["expires_at"] = format_timestamp(self.expires_at)
        elif self.expires_at is not None:
            raise MemoryValidationError(
                f"{tier.value.capitalize()} memory entries cannot expire."
            )
        return value

    @classmethod
    def from_json(cls, value: Any, tier: MemoryTier) -> MemoryEntry:
        if not isinstance(value, dict):
            raise MemoryValidationError("Each memory entry must be a JSON object.")

        expected = {
            "id",
            "text",
            "tags",
            "source",
            "created_at",
            "updated_at",
        }
        if tier is MemoryTier.TEMPORARY:
            expected.add("expires_at")
        _require_keys(value, expected, "Memory entry")

        tags = value["tags"]
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise MemoryValidationError("Memory entry tags must be a list of strings.")

        expires_at = None
        if tier is MemoryTier.TEMPORARY:
            expires_at = parse_timestamp(value["expires_at"], "expires_at")

        return cls(
            id=value["id"],
            text=value["text"],
            tags=tuple(tags),
            source=value["source"],
            created_at=parse_timestamp(value["created_at"], "created_at"),
            updated_at=parse_timestamp(value["updated_at"], "updated_at"),
            expires_at=expires_at,
        )


@dataclass(frozen=True, slots=True)
class MemoryDocument:
    tier: MemoryTier
    updated_at: datetime
    entries: tuple[MemoryEntry, ...]
    session_id: str | None = None
    started_at: datetime | None = None

    def __post_init__(self) -> None:
        try:
            tier = MemoryTier(self.tier)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("Unknown memory tier.") from exc
        object.__setattr__(self, "tier", tier)
        object.__setattr__(self, "updated_at", require_utc(self.updated_at, "updated_at"))

        try:
            entries = tuple(self.entries)
        except TypeError as exc:
            raise MemoryValidationError("Document entries must be a sequence.") from exc
        if any(not isinstance(entry, MemoryEntry) for entry in entries):
            raise MemoryValidationError("Document entries must be memory entries.")
        object.__setattr__(self, "entries", entries)

        if len({entry.id for entry in entries}) != len(entries):
            raise MemoryValidationError("Memory entry IDs must be unique within a file.")

        for entry in entries:
            if tier is MemoryTier.TEMPORARY and entry.expires_at is None:
                raise MemoryValidationError(
                    "Temporary memory entries require expires_at."
                )
            if tier is not MemoryTier.TEMPORARY and entry.expires_at is not None:
                raise MemoryValidationError(
                    f"{tier.value.capitalize()} memory entries cannot expire."
                )

        if tier is MemoryTier.SESSION:
            try:
                session_id = str(uuid.UUID(self.session_id or ""))
            except (AttributeError, TypeError, ValueError) as exc:
                raise MemoryValidationError("Session memory requires a UUID session_id.") from exc
            object.__setattr__(self, "session_id", session_id)
            if self.started_at is None:
                raise MemoryValidationError("Session memory requires started_at.")
            object.__setattr__(
                self, "started_at", require_utc(self.started_at, "started_at")
            )
        elif self.session_id is not None or self.started_at is not None:
            raise MemoryValidationError(
                "Only session memory documents may contain session metadata."
            )

    @classmethod
    def empty(
        cls,
        tier: MemoryTier,
        *,
        now: datetime | None = None,
        session_id: str | None = None,
        started_at: datetime | None = None,
    ) -> MemoryDocument:
        try:
            tier = MemoryTier(tier)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("Unknown memory tier.") from exc
        current = require_utc(now or utc_now(), "now")
        if tier is MemoryTier.SESSION:
            return cls(
                tier=tier,
                updated_at=current,
                entries=(),
                session_id=session_id or str(uuid.uuid4()),
                started_at=started_at or current,
            )
        return cls(tier=tier, updated_at=current, entries=())

    def to_json(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "tier": self.tier.value,
            "updated_at": format_timestamp(self.updated_at),
            "entries": [entry.to_json(self.tier) for entry in self.entries],
        }
        if self.tier is MemoryTier.SESSION:
            value["session_id"] = self.session_id
            value["started_at"] = format_timestamp(self.started_at)
        return value

    @classmethod
    def from_json(
        cls,
        value: Any,
        expected_tier: MemoryTier,
    ) -> MemoryDocument:
        try:
            expected_tier = MemoryTier(expected_tier)
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("Unknown expected memory tier.") from exc
        if not isinstance(value, dict):
            raise MemoryValidationError("Memory file must contain a JSON object.")

        expected = {"schema_version", "tier", "updated_at", "entries"}
        if expected_tier is MemoryTier.SESSION:
            expected.update({"session_id", "started_at"})
        _require_keys(value, expected, "Memory document")

        version = value["schema_version"]
        if not isinstance(version, int) or isinstance(version, bool):
            raise MemoryValidationError("schema_version must be an integer.")
        if version != SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"Unsupported memory schema version {version}; "
                f"this version supports {SCHEMA_VERSION}."
            )

        try:
            tier = MemoryTier(value["tier"])
        except (TypeError, ValueError) as exc:
            raise MemoryValidationError("Memory document has an unknown tier.") from exc
        if tier is not expected_tier:
            raise MemoryValidationError(
                f"Expected a {expected_tier.value} memory file, found {tier.value}."
            )

        raw_entries = value["entries"]
        if not isinstance(raw_entries, list):
            raise MemoryValidationError("Memory document entries must be a list.")

        entries = tuple(MemoryEntry.from_json(item, tier) for item in raw_entries)
        return cls(
            tier=tier,
            updated_at=parse_timestamp(value["updated_at"], "updated_at"),
            entries=entries,
            session_id=value.get("session_id"),
            started_at=(
                parse_timestamp(value["started_at"], "started_at")
                if tier is MemoryTier.SESSION
                else None
            ),
        )

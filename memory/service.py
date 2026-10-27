"""Local JSON storage for session, temporary, and permanent memories."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tempfile
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from memory.models import (
    MemoryConflictError,
    MemoryDocument,
    MemoryEntry,
    MemoryEntryNotFoundError,
    MemorySource,
    MemoryStorageError,
    MemoryTier,
    MemoryValidationError,
    require_utc,
    utc_now,
)
from memory.paths import MemoryPaths


TEMPORARY_DEFAULT_TTL = timedelta(days=30)
_SEARCH_WORD = re.compile(r"[\w]+", re.UNICODE)
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MemoryMatch:
    tier: MemoryTier
    entry: MemoryEntry
    score: int


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def _read_raw(path: Path) -> bytes | None:
    try:
        file_stat = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise MemoryStorageError(f"Could not inspect memory file {path}.") from exc

    if stat.S_ISLNK(file_stat.st_mode):
        raise MemoryStorageError(f"Memory file must not be a symbolic link: {path}")
    if not stat.S_ISREG(file_stat.st_mode):
        raise MemoryStorageError(f"Memory path is not a regular file: {path}")

    try:
        raw = path.read_bytes()
        path.chmod(0o600)
        return raw
    except OSError as exc:
        raise MemoryStorageError(f"Could not read memory file {path}.") from exc


def _atomic_write(path: Path, document: MemoryDocument) -> None:
    try:
        serialized = json.dumps(
            document.to_json(),
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError, MemoryValidationError) as exc:
        raise MemoryValidationError("Memory document could not be serialized.") from exc

    temporary_path: Path | None = None
    try:
        _ensure_private_directory(path.parent)
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".jarvis-memory-",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)

        with os.fdopen(file_descriptor, "wb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(serialized)
            output.flush()
            os.fsync(output.fileno())

        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as exc:
        raise MemoryStorageError(f"Could not safely write memory file {path}.") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def _coerce_tier(tier: MemoryTier | str) -> MemoryTier:
    try:
        return MemoryTier(tier)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError(f"Unknown memory tier: {tier!r}.") from exc


def _coerce_source(source: MemorySource | str) -> MemorySource:
    try:
        return MemorySource(source)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError(
            "Memory source must be 'user' or 'jarvis'."
        ) from exc


def _normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
    if isinstance(tags, str):
        raise MemoryValidationError("Memory entry tags must be a list of strings.")
    try:
        return tuple(tags)
    except TypeError as exc:
        raise MemoryValidationError(
            "Memory entry tags must be a list of strings."
        ) from exc


class MemoryService:
    """Read and mutate all memory tiers through validated JSON documents.

    A service instance represents one running Jarvis session. Use it as a
    context manager or call :meth:`close` during application shutdown.
    """

    def __init__(
        self,
        *,
        data_directory: Path | None = None,
        runtime_directory: Path | None = None,
        use_environment: bool = True,
    ) -> None:
        self._lock = threading.RLock()
        self._closed = False

        paths = MemoryPaths.from_environment(
            data_directory=data_directory,
            runtime_directory=runtime_directory,
            use_environment=use_environment,
        )
        self.data_directory = self._prepare_data_directory(paths.data_directories)
        self.session_file = self._prepare_session_file(paths.session_file)

        self._session_id = str(uuid.uuid4())
        self._session_started_at = utc_now()
        self._session_document = MemoryDocument.empty(
            MemoryTier.SESSION,
            now=self._session_started_at,
            session_id=self._session_id,
            started_at=self._session_started_at,
        )

        if self.session_file is not None:
            # Replace any orphaned file; it must never become this session's memory.
            _atomic_write(self.session_file, self._session_document)

        try:
            self.prune_expired()
        except (MemoryConflictError, MemoryStorageError, MemoryValidationError) as exc:
            # Expiry cleanup is housekeeping; a damaged file must not stop Jarvis.
            _LOGGER.warning("Could not prune expired temporary memory at startup: %s", exc)

    @staticmethod
    def _prepare_data_directory(candidates: tuple[Path, ...]) -> Path:
        last_error: OSError | None = None
        for candidate in candidates:
            try:
                _ensure_private_directory(candidate)
                return candidate
            except OSError as exc:
                last_error = exc

        raise MemoryStorageError(
            "Could not create a private persistent memory directory."
        ) from last_error

    @staticmethod
    def _prepare_session_file(candidate: Path | None) -> Path | None:
        if candidate is None:
            return None
        try:
            _ensure_private_directory(candidate.parent)
            return candidate
        except OSError:
            # Session data can remain in RAM when the runtime directory is unavailable.
            return None

    def __enter__(self) -> MemoryService:
        self._ensure_open()
        return self

    @property
    def protected_paths(self) -> tuple[Path, ...]:
        """Paths the terminal sandbox must hide from arbitrary commands."""
        return tuple(
            path
            for path in (self.data_directory, self.session_file)
            if path is not None
        )

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise MemoryStorageError("Memory service is closed.")

    def _path_for(self, tier: MemoryTier) -> Path | None:
        if tier is MemoryTier.SESSION:
            return self.session_file
        return self.data_directory / f"{tier.value}.json"

    def _empty_document(self, tier: MemoryTier) -> MemoryDocument:
        if tier is MemoryTier.SESSION:
            return MemoryDocument.empty(
                tier,
                session_id=self._session_id,
                started_at=self._session_started_at,
            )
        return MemoryDocument.empty(tier)

    def _load_document(
        self,
        tier: MemoryTier,
    ) -> tuple[MemoryDocument, bytes | None]:
        path = self._path_for(tier)
        if path is None:
            return self._session_document, None

        raw = _read_raw(path)
        if raw is None:
            return self._empty_document(tier), None

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MemoryValidationError(
                f"Memory file {path} is not valid UTF-8 JSON; it was left unchanged."
            ) from exc

        document = MemoryDocument.from_json(payload, tier)
        if tier is MemoryTier.SESSION and document.session_id != self._session_id:
            raise MemoryConflictError(
                "The active session file belongs to a different Jarvis session."
            )
        return document, raw

    def _save_document(
        self,
        tier: MemoryTier,
        document: MemoryDocument,
        expected_raw: bytes | None,
    ) -> None:
        path = self._path_for(tier)
        if path is None:
            self._session_document = document
            return

        current_raw = _read_raw(path)
        if current_raw != expected_raw:
            raise MemoryConflictError(
                f"Memory file {path} changed during the operation; no update was written."
            )

        _atomic_write(path, document)
        if tier is MemoryTier.SESSION:
            self._session_document = document

    def list_entries(
        self,
        tier: MemoryTier | str,
    ) -> tuple[MemoryEntry, ...]:
        tier = _coerce_tier(tier)
        with self._lock:
            self._ensure_open()
            document, _ = self._load_document(tier)
            now = utc_now()
            return tuple(
                entry for entry in document.entries if not entry.is_expired(now)
            )

    def get_entry(
        self,
        tier: MemoryTier | str,
        entry_id: str,
    ) -> MemoryEntry | None:
        tier = _coerce_tier(tier)
        with self._lock:
            self._ensure_open()
            document, _ = self._load_document(tier)
            now = utc_now()
            return next(
                (
                    entry
                    for entry in document.entries
                    if entry.id == entry_id and not entry.is_expired(now)
                ),
                None,
            )

    def search_entries(
        self,
        query: str,
        *,
        tier: MemoryTier | str | None = None,
        limit: int = 5,
    ) -> tuple[MemoryMatch, ...]:
        if not isinstance(query, str) or not query.strip():
            raise MemoryValidationError("Memory search query must not be empty.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise MemoryValidationError("Memory search limit must be between 1 and 10.")

        selected_tiers = (
            tuple(MemoryTier)
            if tier is None
            else (_coerce_tier(tier),)
        )
        query_text = query.strip().casefold()
        query_words = set(_SEARCH_WORD.findall(query_text))
        if not query_words:
            raise MemoryValidationError("Memory search query must contain a word.")

        with self._lock:
            self._ensure_open()
            now = utc_now()
            ranked: list[tuple[int, datetime, MemoryTier, MemoryEntry]] = []
            for selected_tier in selected_tiers:
                document, _ = self._load_document(selected_tier)
                for entry in document.entries:
                    if entry.is_expired(now):
                        continue

                    text = entry.text.casefold()
                    text_words = set(_SEARCH_WORD.findall(text))
                    tag_words = {
                        word
                        for tag in entry.tags
                        for word in _SEARCH_WORD.findall(tag.casefold())
                    }
                    score = sum(
                        3 if word in tag_words else 2 if word in text_words else 0
                        for word in query_words
                    )
                    if query_text in text:
                        score += 2
                    if score:
                        ranked.append((score, entry.updated_at, selected_tier, entry))

            ranked.sort(key=lambda item: (-item[0], -item[1].timestamp(), item[3].id))
            return tuple(
                MemoryMatch(tier=entry_tier, entry=entry, score=score)
                for score, _, entry_tier, entry in ranked[:limit]
            )

    def add_entry(
        self,
        tier: MemoryTier | str,
        text: str,
        *,
        tags: Iterable[str] = (),
        source: MemorySource | str = MemorySource.JARVIS,
        expires_at: datetime | None = None,
    ) -> MemoryEntry:
        tier = _coerce_tier(tier)
        source = _coerce_source(source)
        now = utc_now()

        if tier is MemoryTier.TEMPORARY:
            if expires_at is None:
                expires_at = now + TEMPORARY_DEFAULT_TTL
            else:
                expires_at = require_utc(expires_at, "expires_at")
            if expires_at <= now:
                raise MemoryValidationError("Temporary memory expiry must be in the future.")
        elif expires_at is not None:
            raise MemoryValidationError(
                f"{tier.value.capitalize()} memory cannot have an expiry."
            )

        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            text=text,
            tags=_normalize_tags(tags),
            source=source,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

        with self._lock:
            self._ensure_open()
            document, raw = self._load_document(tier)
            updated = replace(
                document,
                updated_at=now,
                entries=(*document.entries, entry),
            )
            self._save_document(tier, updated, raw)
        return entry

    def update_entry(
        self,
        tier: MemoryTier | str,
        entry_id: str,
        *,
        text: str | None = None,
        tags: Iterable[str] | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryEntry:
        tier = _coerce_tier(tier)
        if text is None and tags is None and expires_at is None:
            raise MemoryValidationError("Provide at least one memory field to update.")
        if tier is not MemoryTier.TEMPORARY and expires_at is not None:
            raise MemoryValidationError(
                f"{tier.value.capitalize()} memory cannot have an expiry."
            )

        now = utc_now()
        if expires_at is not None:
            expires_at = require_utc(expires_at, "expires_at")
            if expires_at <= now:
                raise MemoryValidationError("Temporary memory expiry must be in the future.")

        with self._lock:
            self._ensure_open()
            document, raw = self._load_document(tier)
            entries = list(document.entries)
            index = next(
                (position for position, entry in enumerate(entries) if entry.id == entry_id),
                None,
            )
            if index is None:
                raise MemoryEntryNotFoundError(f"No {tier.value} memory has ID {entry_id}.")

            current = entries[index]
            updated_entry = replace(
                current,
                text=current.text if text is None else text,
                tags=current.tags if tags is None else _normalize_tags(tags),
                updated_at=now,
                expires_at=current.expires_at if expires_at is None else expires_at,
            )
            entries[index] = updated_entry
            updated_document = replace(
                document,
                updated_at=now,
                entries=tuple(entries),
            )
            self._save_document(tier, updated_document, raw)
        return updated_entry

    def delete_entry(
        self,
        tier: MemoryTier | str,
        entry_id: str,
    ) -> bool:
        tier = _coerce_tier(tier)
        with self._lock:
            self._ensure_open()
            document, raw = self._load_document(tier)
            entries = tuple(entry for entry in document.entries if entry.id != entry_id)
            if len(entries) == len(document.entries):
                return False

            updated = replace(
                document,
                updated_at=utc_now(),
                entries=entries,
            )
            self._save_document(tier, updated, raw)
            return True

    def prune_expired(self) -> int:
        with self._lock:
            self._ensure_open()
            document, raw = self._load_document(MemoryTier.TEMPORARY)
            now = utc_now()
            entries = tuple(
                entry for entry in document.entries if not entry.is_expired(now)
            )
            removed = len(document.entries) - len(entries)
            if removed:
                self._save_document(
                    MemoryTier.TEMPORARY,
                    replace(document, updated_at=now, entries=entries),
                    raw,
                )
            return removed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True

            if self.session_file is None:
                return

            try:
                raw = _read_raw(self.session_file)
                if raw is None:
                    return
                payload = json.loads(raw.decode("utf-8"))
                document = MemoryDocument.from_json(payload, MemoryTier.SESSION)
                if document.session_id == self._session_id:
                    self.session_file.unlink(missing_ok=True)
            except FileNotFoundError:
                return
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, MemoryValidationError):
                # Session data is disposable; remove malformed remnants at shutdown.
                try:
                    self.session_file.unlink(missing_ok=True)
                except OSError as exc:
                    raise MemoryStorageError(
                        f"Could not remove session memory file {self.session_file}."
                    ) from exc
            except MemoryStorageError:
                raise

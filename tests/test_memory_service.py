"""Tests for the local JSON memory storage foundation."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from memory import (
    MemoryConflictError,
    MemoryDocument,
    MemoryEntry,
    MemoryEntryNotFoundError,
    MemoryService,
    MemorySource,
    MemoryStorageError,
    MemoryTier,
    MemoryValidationError,
    TEMPORARY_DEFAULT_TTL,
    UnsupportedSchemaVersionError,
)
from memory.models import utc_now
from memory.paths import MemoryPaths


class MemoryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.runtime_directory = self.root / "runtime"
        self.runtime_directory.mkdir()
        self.data_directory = self.root / "data" / "jarvis" / "memory"
        self.service = MemoryService(
            data_directory=self.data_directory,
            runtime_directory=self.runtime_directory,
        )

    def tearDown(self) -> None:
        self.service.close()
        self.temporary_directory.cleanup()

    def test_crud_works_for_all_memory_tiers(self) -> None:
        session = self.service.add_entry(
            MemoryTier.SESSION,
            "Current task is organizing photos.",
            tags=["task"],
            source=MemorySource.USER,
        )
        temporary = self.service.add_entry(
            MemoryTier.TEMPORARY,
            "The borrowed laptop is due back next week.",
            tags=["machine"],
        )
        permanent = self.service.add_entry(
            MemoryTier.PERMANENT,
            "The user prefers concise spoken answers.",
            tags=["preference"],
        )

        self.assertEqual(self.service.get_entry("session", session.id), session)
        self.assertEqual(self.service.get_entry("temporary", temporary.id), temporary)
        self.assertEqual(self.service.get_entry("permanent", permanent.id), permanent)

        updated = self.service.update_entry(
            MemoryTier.PERMANENT,
            permanent.id,
            text="The user prefers concise spoken replies.",
            tags=["preference", "voice"],
        )
        self.assertEqual(updated.text, "The user prefers concise spoken replies.")
        self.assertEqual(updated.tags, ("preference", "voice"))
        self.assertEqual(updated.source, MemorySource.JARVIS)

        self.assertTrue(self.service.delete_entry(MemoryTier.SESSION, session.id))
        self.assertFalse(self.service.delete_entry(MemoryTier.SESSION, session.id))
        with self.assertRaises(MemoryEntryNotFoundError):
            self.service.update_entry(MemoryTier.SESSION, session.id, text="Missing")

        self.assertEqual(self.service.list_entries(MemoryTier.SESSION), ())
        self.assertEqual(len(self.service.list_entries(MemoryTier.TEMPORARY)), 1)
        self.assertEqual(len(self.service.list_entries(MemoryTier.PERMANENT)), 1)

    def test_temporary_memory_gets_default_and_explicit_expiry(self) -> None:
        defaulted = self.service.add_entry(MemoryTier.TEMPORARY, "Short-lived fact")
        self.assertEqual(
            defaulted.expires_at,
            defaulted.created_at + TEMPORARY_DEFAULT_TTL,
        )

        requested_expiry = utc_now() + timedelta(days=5)
        explicit = self.service.add_entry(
            MemoryTier.TEMPORARY,
            "Fact with a requested expiry",
            expires_at=requested_expiry,
        )
        self.assertEqual(explicit.expires_at, requested_expiry)

        with self.assertRaises(MemoryValidationError):
            self.service.add_entry(
                MemoryTier.TEMPORARY,
                "Already expired",
                expires_at=utc_now() - timedelta(seconds=1),
            )
        with self.assertRaises(MemoryValidationError):
            self.service.add_entry(
                MemoryTier.PERMANENT,
                "Permanent facts do not expire",
                expires_at=utc_now() + timedelta(days=5),
            )

    def test_expired_entries_are_hidden_and_pruned(self) -> None:
        now = utc_now()
        expired = MemoryEntry(
            id="0cd28c78-70fc-4679-b100-c6a3b369a97e",
            text="This memory has expired.",
            tags=("temporary",),
            source=MemorySource.USER,
            created_at=now - timedelta(days=31),
            updated_at=now - timedelta(days=31),
            expires_at=now - timedelta(seconds=1),
        )
        document = MemoryDocument(
            tier=MemoryTier.TEMPORARY,
            updated_at=now,
            entries=(expired,),
        )
        path = self.data_directory / "temporary.json"
        path.write_text(json.dumps(document.to_json()), encoding="utf-8")

        self.assertEqual(self.service.list_entries(MemoryTier.TEMPORARY), ())
        self.assertIsNone(self.service.get_entry(MemoryTier.TEMPORARY, expired.id))
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["entries"]), 1)
        self.assertEqual(self.service.prune_expired(), 1)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["entries"], [])
        self.assertEqual(self.service.prune_expired(), 0)

    def test_startup_prunes_expired_temporary_entries(self) -> None:
        now = utc_now()
        expired = MemoryEntry(
            id="e5c280f3-a3a0-4f24-b7ac-a436da93c6a3",
            text="This temporary memory expired before startup.",
            tags=("temporary",),
            source=MemorySource.USER,
            created_at=now - timedelta(days=31),
            updated_at=now - timedelta(days=31),
            expires_at=now - timedelta(seconds=1),
        )
        document = MemoryDocument(
            tier=MemoryTier.TEMPORARY,
            updated_at=now,
            entries=(expired,),
        )
        path = self.data_directory / "temporary.json"
        path.write_text(json.dumps(document.to_json()), encoding="utf-8")

        replacement = MemoryService(
            data_directory=self.data_directory,
            runtime_directory=self.runtime_directory,
        )
        try:
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["entries"],
                [],
            )
            self.assertEqual(replacement.list_entries(MemoryTier.TEMPORARY), ())
        finally:
            replacement.close()

    def test_startup_pruning_warns_but_preserves_malformed_temporary_file(self) -> None:
        path = self.data_directory / "temporary.json"
        original = b'{"entries":'
        path.write_bytes(original)

        with self.assertLogs("memory.service", level="WARNING") as captured:
            replacement = MemoryService(
                data_directory=self.data_directory,
                runtime_directory=self.runtime_directory,
            )
        try:
            self.assertIn("Could not prune expired temporary memory", captured.output[0])
            self.assertEqual(path.read_bytes(), original)
        finally:
            replacement.close()

    def test_malformed_json_is_reported_without_overwriting_it(self) -> None:
        path = self.data_directory / "permanent.json"
        original = b'{"entries":'
        path.write_bytes(original)

        with self.assertRaises(MemoryValidationError):
            self.service.list_entries(MemoryTier.PERMANENT)

        self.assertEqual(path.read_bytes(), original)

    def test_unknown_schema_version_is_rejected(self) -> None:
        path = self.data_directory / "permanent.json"
        payload = {
            "schema_version": 2,
            "tier": "permanent",
            "updated_at": "2026-10-25T09:00:00Z",
            "entries": [],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaises(UnsupportedSchemaVersionError):
            self.service.list_entries(MemoryTier.PERMANENT)

    def test_unknown_entry_fields_are_rejected_without_rewriting_file(self) -> None:
        path = self.data_directory / "permanent.json"
        timestamp = "2026-10-25T09:00:00Z"
        payload = {
            "schema_version": 1,
            "tier": "permanent",
            "updated_at": timestamp,
            "entries": [
                {
                    "id": "be9cad47-8302-4888-9da0-ea44da074ea6",
                    "text": "A stable fact.",
                    "tags": [],
                    "source": "user",
                    "created_at": timestamp,
                    "updated_at": timestamp,
                    "unexpected": "unrecognized field",
                }
            ],
        }
        original = json.dumps(payload).encode("utf-8")
        path.write_bytes(original)

        with self.assertRaises(MemoryValidationError):
            self.service.list_entries(MemoryTier.PERMANENT)

        self.assertEqual(path.read_bytes(), original)

    def test_memory_directories_and_files_are_private(self) -> None:
        self.service.add_entry(MemoryTier.PERMANENT, "A private fact")
        persistent_file = self.data_directory / "permanent.json"

        self.assertEqual(self.data_directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(persistent_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.service.session_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.data_directory.glob(".jarvis-memory-*.tmp")), [])

    def test_session_file_is_replaced_for_a_new_service_and_cleaned_on_close(self) -> None:
        session_file = self.service.session_file
        self.service.add_entry(MemoryTier.SESSION, "Old session note")
        old_session_id = json.loads(session_file.read_text(encoding="utf-8"))["session_id"]

        replacement = MemoryService(
            data_directory=self.data_directory,
            runtime_directory=self.runtime_directory,
        )
        try:
            payload = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertNotEqual(payload["session_id"], old_session_id)
            self.assertEqual(payload["entries"], [])

            self.service.close()
            self.assertTrue(session_file.exists())
        finally:
            replacement.close()

        self.assertFalse(session_file.exists())

    def test_runtime_directory_unavailable_uses_ram_for_session(self) -> None:
        with patch.dict(
            os.environ,
            {"XDG_RUNTIME_DIR": str(self.root / "missing-runtime")},
        ):
            paths = MemoryPaths.from_environment(data_directory=self.data_directory)
            self.assertIsNone(paths.session_file)

            with MemoryService(data_directory=self.data_directory) as service:
                entry = service.add_entry(MemoryTier.SESSION, "RAM-only note")
                self.assertIsNone(service.session_file)
                self.assertEqual(
                    service.get_entry(MemoryTier.SESSION, entry.id),
                    entry,
                )

    def test_unusable_xdg_data_home_falls_back_to_user_data_directory(self) -> None:
        unusable_data_home = self.root / "not-a-directory"
        unusable_data_home.write_text("occupied", encoding="utf-8")
        home = self.root / "home"

        with patch.dict(
            os.environ,
            {
                "HOME": str(home),
                "XDG_DATA_HOME": str(unusable_data_home),
                "XDG_RUNTIME_DIR": "",
            },
        ):
            with MemoryService() as service:
                self.assertEqual(
                    service.data_directory,
                    home / ".local" / "share" / "jarvis" / "memory",
                )

    def test_external_change_during_write_is_not_overwritten(self) -> None:
        with patch(
            "memory.service._read_raw",
            side_effect=[None, b"external edit"],
        ):
            with self.assertRaises(MemoryConflictError):
                self.service.add_entry(MemoryTier.PERMANENT, "New fact")

        self.assertFalse((self.data_directory / "permanent.json").exists())

    def test_context_manager_closes_service(self) -> None:
        service = MemoryService(
            data_directory=self.data_directory,
            runtime_directory=self.runtime_directory,
        )
        session_file = service.session_file
        with service:
            self.assertTrue(session_file.exists())

        self.assertFalse(session_file.exists())
        with self.assertRaises(MemoryStorageError):
            service.add_entry(MemoryTier.PERMANENT, "After close")


if __name__ == "__main__":
    unittest.main()

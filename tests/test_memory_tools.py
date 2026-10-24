"""Tests for model-facing memory tools and bounded memory search."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory import MemoryService, MemoryTier, MemoryValidationError
from tools.memory import MEMORY_TOOLS, create_memory_handlers
from tools.registry import TOOL_HANDLERS, TOOLS, handlers_for, tools_for


class MemoryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        runtime_directory = root / "runtime"
        runtime_directory.mkdir()
        self.service = MemoryService(
            data_directory=root / "data" / "memory",
            runtime_directory=runtime_directory,
        )
        self.handlers = create_memory_handlers(self.service)

    def tearDown(self) -> None:
        self.service.close()
        self.temporary_directory.cleanup()

    def test_registry_exposes_memory_tools_only_with_a_service(self) -> None:
        self.assertEqual(tools_for(), TOOLS)
        self.assertEqual(handlers_for().keys(), TOOL_HANDLERS.keys())
        self.assertEqual(tools_for(self.service), [*TOOLS, *MEMORY_TOOLS])
        self.assertTrue(set(self.handlers).issubset(handlers_for(self.service)))

    def test_memory_tool_schemas_are_strict_and_have_required_arguments(self) -> None:
        for schema in MEMORY_TOOLS:
            with self.subTest(tool=schema["name"]):
                parameters = schema["parameters"]
                self.assertTrue(schema["strict"])
                self.assertFalse(parameters["additionalProperties"])
                self.assertEqual(
                    set(parameters["properties"]),
                    set(parameters["required"]),
                )

    def test_crud_tools_operate_on_service_entries(self) -> None:
        added = self.handlers["add_memory"](
            tier="temporary",
            text="Laptop borrowed until November.",
            tags=["machine", "laptop"],
            expires_at=None,
        )
        self.assertTrue(added["success"])
        self.assertIsNotNone(added["expires_at"])

        found = self.handlers["search_memory"](
            query="borrowed laptop",
            tier=None,
            limit=5,
        )
        self.assertEqual(len(found["results"]), 1)
        self.assertEqual(found["results"][0]["id"], added["id"])
        self.assertEqual(found["results"][0]["tier"], "temporary")

        updated = self.handlers["update_memory"](
            tier="temporary",
            id=added["id"],
            text="Laptop loan ends next week.",
            tags=[],
            expires_at=None,
        )
        self.assertTrue(updated["success"])
        entry = self.service.get_entry(MemoryTier.TEMPORARY, added["id"])
        self.assertEqual(entry.text, "Laptop loan ends next week.")
        self.assertEqual(entry.tags, ())

        deleted = self.handlers["delete_memory"](
            tier="temporary",
            id=added["id"],
        )
        self.assertTrue(deleted["success"])
        self.assertIsNone(
            self.service.get_entry(MemoryTier.TEMPORARY, added["id"])
        )

    def test_search_caps_result_count_and_text_size(self) -> None:
        long_text = "DistinctiveNote " + ("detail " * 150)
        entry = self.service.add_entry(
            MemoryTier.PERMANENT,
            long_text,
            tags=[
                "DistinctiveNote",
                *(f"{index}-" + "t" * 100 for index in range(13)),
            ],
        )

        result = self.handlers["search_memory"](
            query="DistinctiveNote",
            tier="permanent",
            limit=1,
        )

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["id"], entry.id)
        self.assertLessEqual(len(result["results"][0]["text"]), 600)
        self.assertTrue(result["results"][0]["truncated"])
        self.assertEqual(len(result["results"][0]["tags"]), 12)
        self.assertTrue(result["results"][0]["tags_truncated"])
        self.assertTrue(all(len(tag) <= 80 for tag in result["results"][0]["tags"]))

    def test_search_rejects_blank_query_and_limit_outside_bounds(self) -> None:
        for query, limit in (("   ", 5), ("fact", 0), ("fact", 11)):
            with self.subTest(query=query, limit=limit):
                with self.assertRaises(MemoryValidationError):
                    self.handlers["search_memory"](
                        query=query,
                        tier=None,
                        limit=limit,
                    )


if __name__ == "__main__":
    unittest.main()

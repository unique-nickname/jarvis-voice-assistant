"""Model-facing operations for the local memory service."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from memory import MemoryService, MemoryTier
from memory.models import format_timestamp, parse_timestamp


_MEMORY_TIERS = ["session", "temporary", "permanent"]
_SEARCH_RESULT_TEXT_LIMIT = 600
_SEARCH_RESULT_TAG_LIMIT = 12
_SEARCH_RESULT_TAG_TEXT_LIMIT = 80


MEMORY_TOOLS = [
    {
        "type": "function",
        "name": "search_memory",
        "description": (
            "Search Jarvis's session, temporary, and permanent memory for "
            "facts relevant to the user's request. Search before answering "
            "questions about remembered user preferences, machine details, "
            "or active tasks. Expired temporary memories are not returned."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "A few distinctive words describing the fact to find.",
                },
                "tier": {
                    "type": ["string", "null"],
                    "enum": [*_MEMORY_TIERS, None],
                    "description": "Memory tier to search, or null to search all tiers.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Maximum number of matches to return.",
                },
            },
            "required": ["query", "tier", "limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "add_memory",
        "description": (
            "Save one concise, useful fact in session, temporary, or permanent "
            "memory. Use session for the current task, temporary for a fact "
            "that should expire, and permanent for stable user or machine "
            "details. A null expiry gives temporary memory its default lifetime "
            "of 30 days."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": _MEMORY_TIERS,
                },
                "text": {
                    "type": "string",
                    "description": "One concise fact or useful note.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Short retrieval tags; use an empty array if none apply.",
                },
                "expires_at": {
                    "type": ["string", "null"],
                    "description": (
                        "UTC RFC 3339 expiry for temporary memory, or null to "
                        "use its 30-day default. Use null for other tiers."
                    ),
                },
            },
            "required": ["tier", "text", "tags", "expires_at"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "update_memory",
        "description": (
            "Edit an existing memory by tier and ID. Pass null for fields "
            "that should remain unchanged. Use an empty tags array to clear "
            "tags. A null expiry leaves a temporary memory's current expiry unchanged."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "tier": {"type": "string", "enum": _MEMORY_TIERS},
                "id": {"type": "string", "description": "Memory entry UUID."},
                "text": {"type": ["string", "null"]},
                "tags": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
                "expires_at": {
                    "type": ["string", "null"],
                    "description": "New temporary expiry in UTC, or null to leave it unchanged.",
                },
            },
            "required": ["tier", "id", "text", "tags", "expires_at"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "delete_memory",
        "description": "Delete one memory entry by tier and ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "tier": {"type": "string", "enum": _MEMORY_TIERS},
                "id": {"type": "string", "description": "Memory entry UUID."},
            },
            "required": ["tier", "id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def _parse_expiry(value: str | None) -> datetime | None:
    if value is None:
        return None
    return parse_timestamp(value, "expires_at")


def _entry_result(entry, tier: MemoryTier) -> dict[str, Any]:
    tags = [
        tag[:_SEARCH_RESULT_TAG_TEXT_LIMIT]
        for tag in entry.tags[:_SEARCH_RESULT_TAG_LIMIT]
    ]
    tags_truncated = len(entry.tags) > _SEARCH_RESULT_TAG_LIMIT or any(
        len(tag) > _SEARCH_RESULT_TAG_TEXT_LIMIT
        for tag in entry.tags[:_SEARCH_RESULT_TAG_LIMIT]
    )
    return {
        "id": entry.id,
        "tier": tier.value,
        "text": entry.text,
        "tags": tags,
        "tags_truncated": tags_truncated,
        "source": entry.source.value,
        "created_at": format_timestamp(entry.created_at),
        "updated_at": format_timestamp(entry.updated_at),
        "expires_at": (
            format_timestamp(entry.expires_at) if entry.expires_at is not None else None
        ),
    }


def _search_memory(
    service: MemoryService,
    query: str,
    tier: str | None,
    limit: int,
) -> dict[str, Any]:
    matches = service.search_entries(query, tier=tier, limit=limit)
    results = []
    for match in matches:
        entry = match.entry
        text = entry.text
        truncated = len(text) > _SEARCH_RESULT_TEXT_LIMIT
        if truncated:
            text = text[:_SEARCH_RESULT_TEXT_LIMIT - 1].rstrip() + "…"
        result = _entry_result(entry, match.tier)
        result["text"] = text
        if truncated:
            result["truncated"] = True
        results.append(result)
    return {"success": True, "results": results}


def create_memory_handlers(service: MemoryService) -> dict[str, Any]:
    """Bind memory tool functions to one active service instance."""

    def search_memory(query: str, tier: str | None, limit: int) -> dict[str, Any]:
        return _search_memory(service, query, tier, limit)

    def add_memory(
        tier: str,
        text: str,
        tags: list[str],
        expires_at: str | None,
    ) -> dict[str, Any]:
        memory_tier = MemoryTier(tier)
        entry = service.add_entry(
            memory_tier,
            text,
            tags=tags,
            source="jarvis",
            expires_at=_parse_expiry(expires_at),
        )
        return {
            "success": True,
            "id": entry.id,
            "tier": memory_tier.value,
            "expires_at": (
                format_timestamp(entry.expires_at)
                if entry.expires_at is not None
                else None
            ),
        }

    def update_memory(
        tier: str,
        id: str,
        text: str | None,
        tags: list[str] | None,
        expires_at: str | None,
    ) -> dict[str, Any]:
        memory_tier = MemoryTier(tier)
        entry = service.update_entry(
            memory_tier,
            id,
            text=text,
            tags=tags,
            expires_at=_parse_expiry(expires_at),
        )
        return {"success": True, "id": entry.id, "tier": memory_tier.value}

    def delete_memory(tier: str, id: str) -> dict[str, Any]:
        memory_tier = MemoryTier(tier)
        deleted = service.delete_entry(memory_tier, id)
        return {
            "success": deleted,
            "deleted_id": id if deleted else None,
            "error": None if deleted else "Memory entry not found.",
        }

    return {
        "search_memory": search_memory,
        "add_memory": add_memory,
        "update_memory": update_memory,
        "delete_memory": delete_memory,
    }

# Memory design baseline

**Status:** The storage foundation and model-facing memory tools are implemented. The main voice loop, text REPL, and legacy push-to-talk loop create one memory service for the process and close it during shutdown. Memory is retrieved on demand through bounded search; automatic transcript summarization and unconditional prompt injection are not implemented.

This document records the agreed starting point for adding memory to Jarvis. It should be updated if implementation reveals a concrete reason to change a decision.

## Goals

- Keep three distinct memory tiers: session, temporary, and permanent.
- Store temporary and permanent memory as local, human-editable JSON outside the repository.
- Let Jarvis perform structured create, read, update, and delete operations on memory entries.
- Supply relevant memory to assistant requests through bounded, on-demand search.
- Keep session memory from being loaded into a later session.

## File locations

Persistent data belongs outside the repository:

- `temporary.json` and `permanent.json` live in `${XDG_DATA_HOME}/jarvis/memory/`, falling back to `~/.local/share/jarvis/memory/` when `XDG_DATA_HOME` is unset or unusable.
- `session.json` lives in `${XDG_RUNTIME_DIR}/jarvis/memory/` while Jarvis is running.
- If `XDG_RUNTIME_DIR` is unavailable, keep session memory in process memory rather than placing it in a persistent directory.

Create the memory directory with owner-only access and files with owner-only read/write access. Memory data must not be stored under the Git worktree by default.

## JSON shape

Each file has a versioned envelope and an `entries` array. Timestamps use UTC RFC 3339 strings. Each entry is one concise fact or useful note, with a stable UUID so it can be edited or removed independently.

```json
{
  "schema_version": 1,
  "tier": "temporary",
  "updated_at": "2026-10-25T09:00:00Z",
  "entries": [
    {
      "id": "e9a74ed9-1a33-41a5-9476-1382497e6f19",
      "text": "The user is borrowing a different laptop until November 10.",
      "tags": ["machine", "laptop"],
      "source": "user",
      "created_at": "2026-10-25T09:00:00Z",
      "updated_at": "2026-10-25T09:00:00Z",
      "expires_at": "2026-11-10T23:59:59Z"
    }
  ]
}
```

`source` is `user` or `jarvis`. Temporary entries require `expires_at`; permanent entries do not have it. A session envelope also records a `session_id` and `started_at`. Session entries do not need expiration timestamps because their lifetime is the session.

## Expiry policy

- Temporary memory expires 30 days after creation by default.
- A user-specified expiry takes precedence over the default.
- Every temporary entry has an explicit `expires_at`; permanent entries have no automatic expiry.
- Expired entries are excluded from retrieval immediately and pruned when a memory service starts. If startup pruning encounters malformed or inaccessible temporary memory, it logs a warning and leaves the file unchanged so Jarvis can still start.

## Session lifecycle

1. On startup, discard any leftover `session.json`; never load it into a new session.
2. Create a fresh session file in the runtime directory when that directory is available. Re-read the file for memory operations so user edits made during the session can be observed.
3. On graceful shutdown, delete the session file.
4. A hard kill or power loss can prevent shutdown cleanup. In that case a stale file may remain until the next start, when it is discarded. If this limitation is unacceptable, session memory must be RAM-only.

Jarvis assumes one running process, as intended for this private application. The active entrypoint creates one `MemoryService`, shares its bound handlers across assistant calls, and closes it on shutdown. No cross-process lock is used. Running two instances remains unsupported because they would compete for the session file and may overwrite persistent changes.

## Service and edit behavior

- A memory service owns path resolution, JSON validation, expiry, and atomic writes. Assistant and tool code must use that service rather than open memory files directly.
- `memory.MemoryService` provides `list_entries`, `get_entry`, `search_entries`, `add_entry`, `update_entry`, `delete_entry`, `prune_expired`, and `close`. Use it as a context manager or call `close` during shutdown.
- Persistent JSON files are created on first write. A missing persistent file is treated as an empty store.
- Memory tools address an entry by tier and ID. The model does not choose paths or edit arbitrary JSON files.
- User edits to the JSON files are supported. Reload before memory operations and detect conflicting changes instead of silently overwriting them.
- Write through a temporary file in the same directory and atomically replace the target file. If JSON is malformed, preserve it and report the validation error; do not silently replace it with an empty store.
- `tools/memory.py` defines strict schemas and service-bound handlers for searching, adding, updating, and deleting entries. The assistant sees these tools only when an entrypoint supplies its active service.
- Search uses word and tag matches, returns at most ten entries, truncates each result's text to 600 characters, and caps returned tags at twelve per entry and 80 characters each. Search results are returned only when a memory tool is called; the application does not inject complete files into each prompt.
- Memory text is untrusted data, not instructions. Assistant instructions explicitly say to ignore commands embedded in retrieved memory.
- Retrieved memories included in a request are sent to the configured OpenAI API. Retrieval should therefore be selective, even though storage is local.

## Deferred decisions

- Whether 30 days remains the right default after using temporary memory in practice.
- How memory extraction should work in more detail. The assistant has basic prompt guidance for saving concise useful facts, but there is no transcript summarizer or memory confirmation policy beyond ordinary tool-use behavior.
- Whether memory backups or undo history are wanted. They should not be added invisibly because they can retain deleted entries.

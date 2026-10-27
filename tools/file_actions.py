"""Bounded search and safe opening of user-selected files in the home folder."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


_MAX_RESULTS = 20
_MAX_VISITED_ENTRIES = 8_000
_MAX_DEPTH = 8
_SEARCH_SECONDS = 3.0
_OPENABLE_EXTENSIONS = frozenset({
    ".csv",
    ".jpeg",
    ".jpg",
    ".md",
    ".mp3",
    ".mp4",
    ".odg",
    ".odp",
    ".ods",
    ".odt",
    ".pdf",
    ".png",
    ".pptx",
    ".txt",
    ".webp",
    ".xlsx",
    ".docx",
})
_SKIPPED_DIRECTORIES = frozenset({
    "node_modules",
    "proc",
    "sys",
    "dev",
    ".cache",
})


def _home_directory() -> Path:
    return Path.home().resolve()


def _resolve_home_path(path: str | None) -> Path:
    home = _home_directory()
    if path is None or not path.strip():
        return home

    candidate = Path(path.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = home / candidate
    resolved = candidate.resolve(strict=True)
    resolved.relative_to(home)
    return resolved


def search_files(
    name_query: str,
    directory: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search filenames under the user's home directory, without reading files."""
    if not isinstance(name_query, str):
        return {"success": False, "error": "The filename query must be text."}
    query = name_query.strip().casefold()
    if (
        not query
        or len(query) > 100
        or "/" in query
        or "\\" in query
        or any(ord(character) < 32 for character in query)
    ):
        return {
            "success": False,
            "error": (
                "Use a filename fragment of 1 to 100 characters, "
                "without a path separator."
            ),
        }
    if type(limit) is not int or not 1 <= limit <= _MAX_RESULTS:
        return {
            "success": False,
            "error": f"limit must be between 1 and {_MAX_RESULTS}.",
        }

    if directory is not None and (
        not isinstance(directory, str) or len(directory) > 4_096
    ):
        return {
            "success": False,
            "error": "Search directory must be a path under home.",
        }

    try:
        root = _resolve_home_path(directory)
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "success": False,
            "error": f"Search directory is unavailable or outside home: {exc}",
        }
    if not root.is_dir():
        return {"success": False, "error": "Search location must be a directory."}

    results = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    visited = 0
    deadline = time.monotonic() + _SEARCH_SECONDS
    truncated = False

    while stack and len(results) < limit:
        if visited >= _MAX_VISITED_ENTRIES or time.monotonic() >= deadline:
            truncated = True
            break

        current, depth = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    visited += 1
                    if visited >= _MAX_VISITED_ENTRIES or time.monotonic() >= deadline:
                        truncated = True
                        break
                    if entry.name.startswith("."):
                        continue

                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if (
                                depth < _MAX_DEPTH
                                and entry.name.casefold() not in _SKIPPED_DIRECTORIES
                            ):
                                stack.append((Path(entry.path), depth + 1))
                        elif (
                            entry.is_file(follow_symlinks=False)
                            and query in entry.name.casefold()
                        ):
                            results.append({
                                "name": entry.name[:240],
                                "path": entry.path,
                            })
                            if len(results) >= limit:
                                truncated = True
                                break
                    except OSError:
                        continue
        except OSError:
            continue

    return {
        "success": True,
        "directory": str(root),
        "matches": results,
        "truncated": truncated or bool(stack),
        "entries_checked": visited,
    }


def open_file(path: str) -> dict[str, Any]:
    """Open a supported document or media file under the user's home folder."""
    if not isinstance(path, str) or not path.strip() or len(path) > 4_096:
        return {"success": False, "error": "Provide a file path under the home folder."}

    try:
        resolved = _resolve_home_path(path.strip())
    except (OSError, RuntimeError, ValueError) as exc:
        return {
            "success": False,
            "error": f"File is unavailable or outside home: {exc}",
        }

    if not resolved.is_file():
        return {"success": False, "error": "The selected path is not a regular file."}
    if resolved.suffix.casefold() not in _OPENABLE_EXTENSIONS:
        return {
            "success": False,
            "error": "This file type is not in the supported open-file list.",
        }

    executable = shutil.which("xdg-open")
    if executable is None:
        return {"success": False, "error": "xdg-open is unavailable."}

    try:
        subprocess.Popen(
            [executable, str(resolved)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return {"success": False, "error": f"Could not open the file: {exc}"}

    return {"success": True, "path": str(resolved)}

"""Resolve memory paths without placing personal data in the repository."""

from __future__ import annotations

import os
from os import X_OK, W_OK
from dataclasses import dataclass
from pathlib import Path


def _absolute_environment_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None

    path = Path(value).expanduser()
    return path if path.is_absolute() else None


@dataclass(frozen=True, slots=True)
class MemoryPaths:
    """Candidate persistent directories and the optional session file path."""

    data_directories: tuple[Path, ...]
    session_file: Path | None

    @classmethod
    def from_environment(
        cls,
        *,
        data_directory: Path | None = None,
        runtime_directory: Path | None = None,
        use_environment: bool = True,
    ) -> MemoryPaths:
        fallback = Path.home() / ".local" / "share" / "jarvis" / "memory"

        if data_directory is not None:
            data_directories = (Path(data_directory).expanduser(),)
        elif use_environment:
            xdg_data_home = _absolute_environment_path("XDG_DATA_HOME")
            if xdg_data_home is None:
                data_directories = (fallback,)
            else:
                configured = xdg_data_home / "jarvis" / "memory"
                data_directories = (
                    (configured, fallback) if configured != fallback else (fallback,)
                )
        else:
            data_directories = (fallback,)

        if runtime_directory is not None:
            runtime_root = Path(runtime_directory).expanduser()
        elif use_environment:
            runtime_root = _absolute_environment_path("XDG_RUNTIME_DIR")
        else:
            runtime_root = None

        session_file = None
        if (
            runtime_root is not None
            and runtime_root.is_absolute()
            and runtime_root.is_dir()
            and os.access(runtime_root, W_OK | X_OK)
        ):
            session_file = runtime_root / "jarvis" / "memory" / "session.json"

        return cls(
            data_directories=data_directories,
            session_file=session_file,
        )

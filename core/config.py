"""Resolve Jarvis's local configuration file without exposing its contents."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configuration_file() -> Path:
    """Return the selected .env path, preferring user config when it exists."""
    configured = os.environ.get("JARVIS_CONFIG_FILE", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            raise ValueError("JARVIS_CONFIG_FILE must be an absolute path.")
        return candidate

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_root = Path(xdg_config_home).expanduser() if xdg_config_home else None
    if config_root is None or not config_root.is_absolute():
        config_root = Path.home() / ".config"
    user_configuration = config_root / "jarvis" / ".env"
    project_configuration = PROJECT_ROOT / ".env"

    if user_configuration.is_file():
        return user_configuration
    if project_configuration.is_file():
        return project_configuration
    return user_configuration

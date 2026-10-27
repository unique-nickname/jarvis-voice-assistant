"""Install user-local desktop entries for Jarvis launch modes."""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.config import PROJECT_ROOT


MANAGED_MARKER = "X-Jarvis-Managed=desktop-entry-v1"
APPLICATION_DIRECTORY = "applications"
APPLICATION_ICON = PROJECT_ROOT / "icon.jpg"


@dataclass(frozen=True)
class DesktopEntry:
    filename: str
    name: str
    comment: str
    arguments: tuple[str, ...] = ()
    settings: bool = False


ENTRIES = (
    DesktopEntry(
        "jarvis-project.desktop",
        "Jarvis",
        "Open the Jarvis desktop launcher",
    ),
    DesktopEntry(
        "jarvis-project-headless.desktop",
        "Jarvis (Headless)",
        "Run Jarvis without its desktop windows",
        ("--headless",),
    ),
    DesktopEntry(
        "jarvis-project-indicator.desktop",
        "Jarvis (Indicator only)",
        "Run Jarvis with only its floating status indicator",
        ("--indicator-only",),
    ),
    DesktopEntry(
        "jarvis-project-stop.desktop",
        "Jarvis (Stop)",
        "Stop Jarvis processes from this project checkout",
        ("--stop",),
    ),
    DesktopEntry(
        "jarvis-project-restart.desktop",
        "Jarvis (Restart)",
        "Stop an existing Jarvis instance and open the desktop launcher",
        ("--kill-existing",),
    ),
    DesktopEntry(
        "jarvis-project-restart-headless.desktop",
        "Jarvis (Restart headless)",
        "Stop an existing Jarvis instance and run headless",
        ("--kill-existing", "--headless"),
    ),
    DesktopEntry(
        "jarvis-project-restart-indicator.desktop",
        "Jarvis (Restart indicator only)",
        "Stop an existing Jarvis instance and show only its indicator",
        ("--kill-existing", "--indicator-only"),
    ),
    DesktopEntry(
        "jarvis-project-settings.desktop",
        "Jarvis Settings",
        "Open Jarvis configuration",
        settings=True,
    ),
)


def _applications_directory() -> Path:
    configured = os.environ.get("XDG_DATA_HOME", "").strip()
    data_home = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local/share"
    )
    if not data_home.is_absolute():
        data_home = Path.home() / ".local/share"
    return data_home / APPLICATION_DIRECTORY


def _escape_desktop_value(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\r", "\\r")
    )


def _quote_exec_argument(argument: str) -> str:
    escaped = (
        argument.replace("%", "%%")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
    )
    return f'"{escaped}"'


def _entry_command(entry: DesktopEntry) -> tuple[str, ...]:
    if entry.settings:
        return (
            str(PROJECT_ROOT / ".venv/bin/python"),
            "-m",
            "jarvis_ui.settings",
        )
    return (str(PROJECT_ROOT / "jarvis"), *entry.arguments)


def _render_entry(entry: DesktopEntry) -> str:
    command = " ".join(_quote_exec_argument(arg) for arg in _entry_command(entry))
    lines = [
        "[Desktop Entry]",
        MANAGED_MARKER,
        "Type=Application",
        f"Name={_escape_desktop_value(entry.name)}",
        f"Comment={_escape_desktop_value(entry.comment)}",
        f"Icon={_escape_desktop_value(str(APPLICATION_ICON))}",
        f"Exec={command}",
        f"Path={_escape_desktop_value(str(PROJECT_ROOT))}",
        "Terminal=false",
        "Categories=Utility;",
        "Keywords=assistant;voice;Jarvis;",
        "",
    ]
    return "\n".join(lines)


def _atomic_write(path: Path, contents: str) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(contents)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, 0o644)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _is_managed(contents: str) -> bool:
    return any(line.strip() == MANAGED_MARKER for line in contents.splitlines())


def install_entries() -> int:
    launcher = PROJECT_ROOT / "jarvis"
    python = PROJECT_ROOT / ".venv/bin/python"
    if not launcher.is_file() or not os.access(launcher, os.X_OK):
        raise SystemExit(f"Jarvis launcher is missing or not executable: {launcher}")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise SystemExit(
            f"Jarvis environment is missing; run setup.sh first: {python}"
        )
    if not APPLICATION_ICON.is_file():
        raise SystemExit(f"Jarvis application icon is missing: {APPLICATION_ICON}")

    directory = _applications_directory()
    targets = [directory / entry.filename for entry in ENTRIES]
    for target in targets:
        if target.exists():
            try:
                current = target.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise SystemExit(
                    f"Cannot inspect existing desktop entry {target}: {exc}"
                ) from None
            if not _is_managed(current):
                raise SystemExit(
                    f"Refusing to overwrite an existing unmanaged desktop entry: {target}"
                )

    try:
        directory.mkdir(parents=True, exist_ok=True)
        for entry, target in zip(ENTRIES, targets, strict=True):
            _atomic_write(target, _render_entry(entry))
    except OSError as exc:
        raise SystemExit(f"Could not install Jarvis desktop entries: {exc}") from None
    print(f"Installed {len(ENTRIES)} Jarvis desktop entries in {directory}.")
    print("Hyprlauncher can find them with its desktop finder.")
    return 0


def uninstall_entries() -> int:
    directory = _applications_directory()
    targets = [directory / entry.filename for entry in ENTRIES]
    existing_targets = [target for target in targets if target.exists()]
    for target in existing_targets:
        try:
            current = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(f"Cannot inspect desktop entry {target}: {exc}") from None
        if not _is_managed(current):
            raise SystemExit(
                f"Refusing to remove an unmanaged desktop entry: {target}"
            )
    try:
        for target in existing_targets:
            target.unlink()
    except OSError as exc:
        raise SystemExit(f"Could not remove Jarvis desktop entries: {exc}") from None
    removed = len(existing_targets)
    print(f"Removed {removed} Jarvis desktop entries from {directory}.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage Jarvis desktop launcher entries."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser(
        "install", help="install entries in the current user's application menu"
    )
    actions.add_parser("uninstall", help="remove entries installed by this module")
    arguments = parser.parse_args()
    if arguments.action == "install":
        install_entries()
    else:
        uninstall_entries()


if __name__ == "__main__":
    main()

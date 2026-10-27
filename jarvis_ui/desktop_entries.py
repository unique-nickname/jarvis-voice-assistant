"""Install user-local desktop entries for Jarvis launch modes."""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.config import PROJECT_ROOT


MANAGED_MARKER = "X-Jarvis-Managed=desktop-entry-v1"
ICON_MARKER = "X-Jarvis-Managed=desktop-icon-v1"
THEME_MARKER = "X-Jarvis-Managed=hicolor-index-v1"
APPLICATION_DIRECTORY = "applications"
APPLICATION_ICON = PROJECT_ROOT / "icon.png"
APPLICATION_ICON_NAME = "jarvis"
ICON_RELATIVE_PATH = Path("icons/hicolor/256x256/apps/jarvis.png")
ICON_MARKER_NAME = "jarvis.png.jarvis-managed"
THEME_INDEX_RELATIVE_PATH = Path("icons/hicolor/index.theme")


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


def _data_home() -> Path:
    configured = os.environ.get("XDG_DATA_HOME", "").strip()
    data_home = (
        Path(configured).expanduser()
        if configured
        else Path.home() / ".local/share"
    )
    if not data_home.is_absolute():
        data_home = Path.home() / ".local/share"
    return data_home


def _applications_directory() -> Path:
    return _data_home() / APPLICATION_DIRECTORY


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
        f"Icon={APPLICATION_ICON_NAME}",
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


def _atomic_write_bytes(path: Path, contents: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
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
    return _has_marker(contents, MANAGED_MARKER)


def _has_marker(contents: str, marker: str) -> bool:
    return any(line.strip() == marker for line in contents.splitlines())


def _has_icon_directory(contents: str) -> bool:
    for line in contents.splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "Directories":
            return "256x256/apps" in {
                part.strip() for part in value.split(",")
            }
    return False


def _system_theme_index_contents() -> str:
    configured = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    for directory in configured.split(":"):
        if not directory:
            continue
        candidate = Path(directory).expanduser() / "icons/hicolor/index.theme"
        try:
            contents = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if _has_icon_directory(contents):
            return f"# {THEME_MARKER}\n{contents.lstrip()}"
    raise SystemExit(
        "Could not find a system hicolor index.theme with a 256x256/apps "
        "directory; refusing to create an incomplete user icon theme."
    )


def _check_theme_index(path: Path) -> tuple[bool, str | None]:
    """Return whether an index should be written and the safe contents."""
    if not path.exists():
        return True, _system_theme_index_contents()
    try:
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"Cannot inspect icon theme index {path}: {exc}") from None
    if _has_marker(contents, THEME_MARKER):
        return True, contents
    if _has_icon_directory(contents):
        return False, None
    raise SystemExit(
        "The existing hicolor icon theme index does not include 256x256/apps; "
        f"refusing to change it: {path}"
    )


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
    if APPLICATION_ICON.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise SystemExit(
            f"Jarvis application icon is not a PNG file: {APPLICATION_ICON}"
        )

    data_home = _data_home()
    directory = _applications_directory()
    icon_target = data_home / ICON_RELATIVE_PATH
    icon_marker = icon_target.with_name(ICON_MARKER_NAME)
    theme_index = data_home / THEME_INDEX_RELATIVE_PATH
    create_theme_index, theme_index_contents = _check_theme_index(theme_index)

    if icon_target.exists():
        try:
            marker_contents = icon_marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(
                f"Refusing to replace an unmanaged Jarvis icon {icon_target}: {exc}"
            ) from None
        if marker_contents.strip() != ICON_MARKER:
            raise SystemExit(f"Refusing to replace an unmanaged icon: {icon_target}")
    elif icon_marker.exists():
        try:
            marker_contents = icon_marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(
                f"Cannot inspect icon marker {icon_marker}: {exc}"
            ) from None
        if marker_contents.strip() != ICON_MARKER:
            raise SystemExit(
                f"Refusing to replace an unmanaged icon marker: {icon_marker}"
            )

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
        icon_target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(icon_marker, f"{ICON_MARKER}\n")
        _atomic_write_bytes(icon_target, APPLICATION_ICON.read_bytes())
        if create_theme_index and theme_index_contents is not None:
            _atomic_write(theme_index, theme_index_contents)
        for entry, target in zip(ENTRIES, targets, strict=True):
            _atomic_write(target, _render_entry(entry))
    except OSError as exc:
        raise SystemExit(f"Could not install Jarvis desktop entries: {exc}") from None
    print(
        f"Installed {len(ENTRIES)} Jarvis desktop entries in {directory} "
        f"and icon {icon_target}."
    )
    print("Hyprlauncher can find them with its desktop finder.")
    return 0


def uninstall_entries() -> int:
    directory = _applications_directory()
    data_home = _data_home()
    icon_target = data_home / ICON_RELATIVE_PATH
    icon_marker = icon_target.with_name(ICON_MARKER_NAME)
    theme_index = data_home / THEME_INDEX_RELATIVE_PATH
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
    remove_icon = False
    if icon_marker.exists():
        try:
            marker_contents = icon_marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(
                f"Cannot inspect icon marker {icon_marker}: {exc}"
            ) from None
        if marker_contents.strip() != ICON_MARKER:
            raise SystemExit(
                f"Refusing to remove an unmanaged icon marker: {icon_marker}"
            )
        remove_icon = True
    remove_theme_index = False
    if theme_index.exists():
        try:
            index_contents = theme_index.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit(
                f"Cannot inspect icon theme index {theme_index}: {exc}"
            ) from None
        remove_theme_index = _has_marker(index_contents, THEME_MARKER)
    try:
        for target in existing_targets:
            target.unlink()
        if remove_icon:
            icon_target.unlink(missing_ok=True)
            icon_marker.unlink()
        if remove_theme_index:
            theme_index.unlink()
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

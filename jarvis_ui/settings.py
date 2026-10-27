"""Local configuration window for Jarvis."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from dotenv import dotenv_values, set_key

from core.config import PROJECT_ROOT, configuration_file
from jarvis_ui.theme import apply_theme
from tools.desktop import (
    APPLICATION_ALLOWLIST_ENV,
    DEFAULT_ALLOWED_APPLICATIONS,
    parse_application_allowlist,
    validate_application_allowlist,
)

try:
    import tkinter as tk
    from tkinter import messagebox, ttk
except ImportError as exc:
    tk = None
    messagebox = None
    ttk = None
    TKINTER_ERROR = exc
else:
    TKINTER_ERROR = None


GENERAL_DEFAULTS = {
    "OPENAI_MODEL": "gpt-4.1-mini",
    "JARVIS_UI_THEME": "dark",
    "CONVERSATION_TIMEOUT_SECONDS": "12",
    "STATUS_INDICATOR_ALWAYS_ON_TOP": "true",
    "STATUS_INDICATOR_STYLE": "pill",
    "STATUS_INDICATOR_PERSISTENT": "true",
    "STATUS_INDICATOR_MONITOR": "",
    "STATUS_INDICATOR_WIDTH": "150",
    "STATUS_INDICATOR_HEIGHT": "32",
    "JARVIS_KOKORO_PYTHON": "",
}
TERMINAL_DEFAULTS = {
    "TERMINAL_COMMANDS_ENABLED": "false",
    "TERMINAL_WRITE_ROOT": "~/",
    "TERMINAL_APPROVAL_FLOATING": "auto",
    "TERMINAL_TIER_1_OVERRIDE": "1",
    "TERMINAL_TIER_2_OVERRIDE": "2",
    "TERMINAL_TIER_3_OVERRIDE": "3",
}
CLIP_DEFAULTS = {
    "CLIP_MONITOR": "DP-1",
    "CLIP_DURATION": "60",
    "CLIP_FPS": "60",
    "CLIP_QUALITY": "very_high",
    "CLIP_CODEC": "h264",
    "CLIP_FORMAT": "mp4",
    "CLIP_AUDIO": "default_output|default_input",
    "CLIP_DIRECTORY": "~/Videos/Clips",
}
SECRET_KEY = "OPENAI_API_KEY"


def _available_hyprland_monitors() -> tuple[str, ...]:
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        desktops = {
            name.strip().casefold()
            for variable in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP")
            for name in os.environ.get(variable, "").split(":")
        }
        if "hyprland" not in desktops:
            return ()
    hyprctl = shutil.which("hyprctl")
    if not hyprctl:
        return ()
    try:
        result = subprocess.run(
            [hyprctl, "-j", "monitors"],
            capture_output=True,
            text=True,
            check=False,
            close_fds=True,
            shell=False,
            timeout=1.0,
        )
        monitors = json.loads(result.stdout) if result.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return ()
    if not isinstance(monitors, list):
        return ()
    return tuple(
        monitor["name"]
        for monitor in monitors
        if isinstance(monitor, dict) and isinstance(monitor.get("name"), str)
    )


def _private_configuration_directory(directory: Path) -> None:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
        raise OSError("Jarvis configuration directory is not privately owned.")
    xdg_home = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser()
    if not xdg_home.is_absolute():
        xdg_home = Path.home() / ".config"
    if directory.resolve() != PROJECT_ROOT and directory == xdg_home / "jarvis":
        directory.chmod(0o700)


def save_configuration(values: dict[str, str], *, clear_api_key: bool = False) -> Path:
    """Atomically update selected keys while retaining unrelated .env content."""
    target = configuration_file()
    _private_configuration_directory(target.parent)
    if target.is_symlink():
        raise OSError("Refusing to replace a symbolic-link configuration file.")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".jarvis-env-",
        dir=target.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)

    try:
        if target.exists():
            if not target.is_file() or target.stat().st_uid != os.geteuid():
                raise OSError("Jarvis configuration file is not privately owned.")
            shutil.copyfile(target, temporary_path)
        os.chmod(temporary_path, 0o600)

        for key, value in values.items():
            set_key(temporary_path, key, value, quote_mode="always")

        if clear_api_key:
            set_key(temporary_path, SECRET_KEY, "", quote_mode="always")

        os.replace(temporary_path, target)
        os.chmod(target, 0o600)
        return target
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


class SettingsWindow:
    def __init__(self, root: tk.Tk | None = None) -> None:
        if tk is None:
            raise RuntimeError(
                "Tkinter and the native Tk runtime are unavailable."
            ) from TKINTER_ERROR
        self.root = root or tk.Tk(className="JarvisSettings")
        self.root.title("Jarvis Settings")
        self.root.geometry("710x680")
        self.root.minsize(620, 560)
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        content = ttk.Frame(self.root, padding=14)
        content.grid(row=0, column=0, sticky="nsew")
        self.variables: dict[str, tk.StringVar] = {}
        self.clear_api_key = tk.BooleanVar(value=False)
        self.api_key_configured = False

        try:
            self.config_path = configuration_file()
            parsed = dotenv_values(self.config_path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Jarvis Settings", str(exc), parent=self.root)
            parsed = {}
            self.config_path = Path(".env")

        theme = str(parsed.get("JARVIS_UI_THEME") or "dark").casefold()
        self.palette = apply_theme(self.root, theme)
        self.api_key_configured = bool(parsed.get(SECRET_KEY))
        raw_allowlist = parsed.get(APPLICATION_ALLOWLIST_ENV)
        self.allowlist_error: str | None = None
        if APPLICATION_ALLOWLIST_ENV not in parsed:
            self.application_allowlist = dict(DEFAULT_ALLOWED_APPLICATIONS)
        else:
            try:
                self.application_allowlist = parse_application_allowlist(
                    str(raw_allowlist or "")
                )
            except ValueError as exc:
                self.application_allowlist = dict(DEFAULT_ALLOWED_APPLICATIONS)
                self.allowlist_error = str(exc)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(2, weight=1)
        ttk.Label(
            content,
            text="Jarvis Settings",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text=f"Configuration file: {self.config_path}",
            wraplength=610,
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        notebook = ttk.Notebook(content)
        notebook.grid(row=2, column=0, sticky="nsew")

        general = ttk.Frame(notebook, padding=12)
        applications = ttk.Frame(notebook, padding=12)
        terminal = ttk.Frame(notebook, padding=12)
        clips = ttk.Frame(notebook, padding=12)
        notebook.add(general, text="General")
        notebook.add(applications, text="Applications")
        notebook.add(terminal, text="Terminal safety")
        notebook.add(clips, text="Clipping")

        self._add_fields(general, GENERAL_DEFAULTS, parsed)
        self._add_secret_field(general)
        self._add_application_allowlist(applications)
        self._add_fields(terminal, TERMINAL_DEFAULTS, parsed)
        ttk.Label(
            terminal,
            text=(
                "Tier overrides change approval routing. Downgrading Tier 2 or 3 "
                "can allow writes or deletions inside the configured terminal "
                "root without a prompt."
            ),
            wraplength=560,
            style="Warning.TLabel",
        ).grid(
            row=len(TERMINAL_DEFAULTS),
            column=0,
            columnspan=2,
            sticky="w",
            pady=(12, 0),
        )
        self._add_fields(clips, CLIP_DEFAULTS, parsed)

        footer = ttk.Frame(content)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            text="Changes apply after Jarvis is restarted.",
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Save settings", command=self._save).grid(
            row=0, column=1, padx=(8, 0)
        )
        ttk.Button(footer, text="Close", command=self.root.destroy).grid(
            row=0, column=2, padx=(8, 0)
        )

    def _add_fields(
        self,
        parent: ttk.Frame,
        defaults: dict[str, str],
        parsed: dict[str, str | None],
    ) -> None:
        parent.columnconfigure(1, weight=1)
        for row, (key, default) in enumerate(defaults.items()):
            value = parsed.get(key)
            variable = tk.StringVar(value=default if value is None else str(value))
            self.variables[key] = variable
            ttk.Label(parent, text=key.replace("_", " ").title()).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=5
            )
            if key == "TERMINAL_COMMANDS_ENABLED":
                ttk.Checkbutton(
                    parent,
                    text="Allow Jarvis-generated terminal commands",
                    variable=variable,
                    onvalue="true",
                    offvalue="false",
                ).grid(row=row, column=1, sticky="w", pady=5)
            elif key == "STATUS_INDICATOR_STYLE":
                ttk.Combobox(
                    parent,
                    textvariable=variable,
                    values=("pill", "dot"),
                    state="readonly",
                ).grid(row=row, column=1, sticky="ew", pady=5)
            elif key == "JARVIS_UI_THEME":
                choice = ttk.Combobox(
                    parent,
                    textvariable=variable,
                    values=("dark", "light"),
                    state="readonly",
                )
                choice.grid(row=row, column=1, sticky="ew", pady=5)
                choice.bind("<<ComboboxSelected>>", self._on_theme_selected)
            elif key == "STATUS_INDICATOR_PERSISTENT":
                ttk.Checkbutton(
                    parent,
                    text="Show on all workspaces (Hyprland)",
                    variable=variable,
                    onvalue="true",
                    offvalue="false",
                ).grid(row=row, column=1, sticky="w", pady=5)
            elif key == "STATUS_INDICATOR_MONITOR":
                ttk.Combobox(
                    parent,
                    textvariable=variable,
                    values=_available_hyprland_monitors(),
                    state="normal",
                ).grid(row=row, column=1, sticky="ew", pady=5)
            else:
                ttk.Entry(parent, textvariable=variable).grid(
                    row=row, column=1, sticky="ew", pady=5
                )

    def _add_application_allowlist(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        ttk.Label(
            parent,
            text="Applications Jarvis may open",
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            parent,
            text=(
                "One entry per line: friendly name = executable. Use a command "
                "name from PATH or an absolute executable path. Do not include "
                "arguments or shell commands."
            ),
            wraplength=620,
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(5, 10))

        editor_frame = ttk.Frame(parent)
        editor_frame.grid(row=2, column=0, sticky="nsew")
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        self.application_list_text = tk.Text(
            editor_frame,
            height=18,
            wrap="none",
            undo=True,
            relief="flat",
            padx=10,
            pady=8,
            font=("TkFixedFont", 10),
        )
        self.application_list_text.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(
            editor_frame,
            orient="vertical",
            command=self.application_list_text.yview,
        )
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(
            editor_frame,
            orient="horizontal",
            command=self.application_list_text.xview,
        )
        horizontal.grid(row=1, column=0, sticky="ew")
        self.application_list_text.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )
        if self.application_allowlist:
            entries = [
                f"{name} = {executable}"
                for name, executable in sorted(self.application_allowlist.items())
            ]
            self.application_list_text.insert("1.0", "\n".join(entries))
        self._style_application_editor()
        if self.allowlist_error:
            ttk.Label(
                parent,
                text=(
                    "The saved allowlist was invalid and defaults are shown. "
                    "Save this list or correct it before saving. "
                    f"Details: {self.allowlist_error}"
                ),
                wraplength=620,
                foreground=self.palette["danger"],
            ).grid(row=3, column=0, sticky="w", pady=(8, 0))

    def _style_application_editor(self) -> None:
        self.application_list_text.configure(
            background=self.palette["surface"],
            foreground=self.palette["foreground"],
            insertbackground=self.palette["foreground"],
            selectbackground=self.palette["selection"],
            selectforeground=self.palette["foreground"],
        )

    def _on_theme_selected(self, _event=None) -> None:
        mode = self.variables["JARVIS_UI_THEME"].get()
        self.palette = apply_theme(self.root, mode)
        self._style_application_editor()

    def _parse_application_editor(self) -> dict[str, str]:
        entries: dict[str, str] = {}
        normalized_names: set[str] = set()
        content = self.application_list_text.get("1.0", "end-1c")
        for line_number, raw_line in enumerate(content.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(
                    f"Application entry on line {line_number} needs '='."
                )
            name, executable = line.split("=", 1)
            normalized_name = name.strip().casefold()
            if normalized_name in normalized_names:
                raise ValueError(
                    f"Application name '{name.strip()}' appears more than once."
                )
            normalized_names.add(normalized_name)
            entries[name.strip()] = executable.strip()
        return validate_application_allowlist(entries)

    def _add_secret_field(self, parent: ttk.Frame) -> None:
        row = len(GENERAL_DEFAULTS)
        ttk.Label(parent, text="OpenAI API key").grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.api_key_var = tk.StringVar()
        self.api_key_entry = ttk.Entry(
            parent,
            textvariable=self.api_key_var,
            show="*",
        )
        self.api_key_entry.grid(row=row, column=1, sticky="ew", pady=5)
        parent.columnconfigure(1, weight=1)

        state = (
            "saved key present; leave blank to keep"
            if self.api_key_configured
            else "no key saved"
        )
        self.api_key_status = ttk.Label(parent, text=state)
        self.api_key_status.grid(
            row=row + 1, column=1, sticky="w", pady=(0, 6)
        )
        ttk.Checkbutton(
            parent,
            text="Clear the saved API key",
            variable=self.clear_api_key,
        ).grid(row=row + 2, column=1, sticky="w")
        ttk.Label(
            parent,
            text=(
                "Monitor is a Hyprland output name; blank uses the current monitor. "
                "Width and height apply to pill style."
            ),
            wraplength=560,
        ).grid(row=row + 3, column=1, sticky="w", pady=(4, 0))

    def _validated_values(self) -> dict[str, str]:
        values = {
            key: variable.get().strip()
            for key, variable in self.variables.items()
        }

        if not values["OPENAI_MODEL"]:
            raise ValueError("OPENAI_MODEL cannot be empty.")
        values["JARVIS_UI_THEME"] = values["JARVIS_UI_THEME"].casefold()
        if values["JARVIS_UI_THEME"] not in {"dark", "light"}:
            raise ValueError("Jarvis UI theme must be dark or light.")
        timeout = int(values["CONVERSATION_TIMEOUT_SECONDS"])
        if not 1 <= timeout <= 120:
            raise ValueError("Conversation timeout must be between 1 and 120 seconds.")
        values["CONVERSATION_TIMEOUT_SECONDS"] = str(timeout)
        if values["STATUS_INDICATOR_ALWAYS_ON_TOP"].casefold() not in {
            "true",
            "false",
        }:
            raise ValueError("Status indicator setting must be true or false.")
        values["STATUS_INDICATOR_ALWAYS_ON_TOP"] = values[
            "STATUS_INDICATOR_ALWAYS_ON_TOP"
        ].casefold()
        values["STATUS_INDICATOR_STYLE"] = values[
            "STATUS_INDICATOR_STYLE"
        ].casefold()
        if values["STATUS_INDICATOR_STYLE"] not in {"pill", "dot"}:
            raise ValueError("Status indicator style must be pill or dot.")
        values["STATUS_INDICATOR_PERSISTENT"] = values[
            "STATUS_INDICATOR_PERSISTENT"
        ].casefold()
        if values["STATUS_INDICATOR_PERSISTENT"] not in {"true", "false"}:
            raise ValueError("Show on all workspaces must be true or false.")
        if len(values["STATUS_INDICATOR_MONITOR"]) > 128 or any(
            character in values["STATUS_INDICATOR_MONITOR"]
            for character in "\0\r\n"
        ):
            raise ValueError("Status indicator monitor name is invalid.")
        for key, minimum, maximum in (
            ("STATUS_INDICATOR_WIDTH", 140, 480),
            ("STATUS_INDICATOR_HEIGHT", 22, 80),
        ):
            number = int(values[key])
            if not minimum <= number <= maximum:
                raise ValueError(
                    f"{key} must be between {minimum} and {maximum} pixels."
                )
            values[key] = str(number)

        values["TERMINAL_COMMANDS_ENABLED"] = values[
            "TERMINAL_COMMANDS_ENABLED"
        ].casefold()
        if values["TERMINAL_COMMANDS_ENABLED"] not in {"true", "false"}:
            raise ValueError("Terminal commands setting must be true or false.")
        if not values["TERMINAL_WRITE_ROOT"]:
            raise ValueError("Terminal write root cannot be empty.")
        if values["TERMINAL_APPROVAL_FLOATING"].casefold() not in {
            "auto", "always", "never"
        }:
            raise ValueError(
                "Approval floating mode must be auto, always, or never."
            )
        values["TERMINAL_APPROVAL_FLOATING"] = values[
            "TERMINAL_APPROVAL_FLOATING"
        ].casefold()
        for key in (
            "TERMINAL_TIER_1_OVERRIDE",
            "TERMINAL_TIER_2_OVERRIDE",
            "TERMINAL_TIER_3_OVERRIDE",
        ):
            if values[key] not in {"1", "2", "3"}:
                raise ValueError(f"{key} must be 1, 2, or 3.")

        for key in ("CLIP_DURATION", "CLIP_FPS"):
            number = int(values[key])
            if number < 1:
                raise ValueError(f"{key} must be a positive whole number.")
            values[key] = str(number)
        for key in (
            "CLIP_MONITOR",
            "CLIP_QUALITY",
            "CLIP_CODEC",
            "CLIP_FORMAT",
            "CLIP_AUDIO",
            "CLIP_DIRECTORY",
        ):
            if not values[key]:
                raise ValueError(f"{key} cannot be empty.")
        values[APPLICATION_ALLOWLIST_ENV] = json.dumps(
            self._parse_application_editor(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return values

    def _save(self) -> None:
        try:
            values = self._validated_values()
            api_key = self.api_key_var.get().strip()
            clear_api_key = self.clear_api_key.get()
            if api_key and clear_api_key:
                raise ValueError(
                    "Enter a new API key or select Clear the saved API key, not both."
                )
            if api_key:
                values[SECRET_KEY] = api_key
            saved_path = save_configuration(
                values,
                clear_api_key=clear_api_key,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not save settings", str(exc), parent=self.root)
            return

        self.api_key_var.set("")
        self.api_key_configured = (
            False if clear_api_key else self.api_key_configured or bool(api_key)
        )
        self.clear_api_key.set(False)
        self.api_key_status.configure(
            text=(
                "saved key present; leave blank to keep"
                if self.api_key_configured
                else "no key saved"
            )
        )
        messagebox.showinfo(
            "Settings saved",
            f"Settings were saved to {saved_path}. Restart Jarvis to apply them.",
            parent=self.root,
        )

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    if tk is None:
        raise SystemExit(
            "Jarvis Settings needs Tkinter and the native Tk runtime. "
            "On Arch Linux, install the tk package."
        ) from None
    try:
        SettingsWindow().run()
    except tk.TclError as exc:
        raise SystemExit(f"Could not connect to the desktop display: {exc}") from None


if __name__ == "__main__":
    main()

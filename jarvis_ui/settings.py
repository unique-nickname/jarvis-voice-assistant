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
TIER_POLICY_LABEL_TO_VALUE = {
    "No approval": "1",
    "Always require approval": "2",
    "Automatically deny": "3",
}
TIER_POLICY_VALUE_TO_LABEL = {
    value: label for label, value in TIER_POLICY_LABEL_TO_VALUE.items()
}
TIER_OVERRIDE_LABELS = {
    "TERMINAL_TIER_1_OVERRIDE": "Tier 1 commands",
    "TERMINAL_TIER_2_OVERRIDE": "Tier 2 commands",
    "TERMINAL_TIER_3_OVERRIDE": "Tier 3 commands",
}
TIER_OVERRIDE_HELP = {
    "TERMINAL_TIER_1_OVERRIDE": (
        "Tier 1 is a narrow set of recognized read-only diagnostics, such as "
        "listing files or checking system state. This choice controls how "
        "commands classified as Tier 1 are routed."
    ),
    "TERMINAL_TIER_2_OVERRIDE": (
        "Tier 2 includes requested changes and commands Jarvis does not "
        "recognize. It normally requires your approval each time. Routing it "
        "to No approval allows those commands to run without a prompt inside "
        "the configured sandbox root."
    ),
    "TERMINAL_TIER_3_OVERRIDE": (
        "Tier 3 includes high-risk commands such as deletion or privilege "
        "escalation, and is denied by default. Routing it to an approval or "
        "no-approval policy overrides that default; no-approval can allow "
        "destructive commands inside the configured sandbox root."
    ),
}
TIER_OVERRIDE_KEYS = frozenset(TIER_OVERRIDE_LABELS)
CLIP_DEFAULTS = {
    "CLIP_MONITOR": "DP-1",
    "CLIP_DURATION": "60",
    "CLIP_FPS": "60",
    "CLIP_QUALITY": "very_high",
    "CLIP_CODEC": "h264",
    "CLIP_FORMAT": "mp4",
    "CLIP_SYSTEM_AUDIO": "true",
    "CLIP_AUDIO": "",
    "CLIP_DIRECTORY": "~/Videos/Clips",
}
NO_MICROPHONE_LABEL = "No microphone"
CLIP_AUDIO_LABEL_TO_VALUE = {
    NO_MICROPHONE_LABEL: "",
    "Default microphone": "default_input",
}
CUSTOM_CLIP_AUDIO_LABEL = "Saved microphone (not currently detected)"
VOICE_DEFAULTS = {
    "JARVIS_TTS_DEVICE": "auto",
    "JARVIS_TTS_CPU_THREADS": "2",
    "VOICE_SILENCE_SECONDS": "2.0",
    "VOICE_MAX_UTTERANCE_SECONDS": "45",
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


def _available_clipping_microphones() -> dict[str, str]:
    pulse_sources: set[str] | None = None
    pactl = shutil.which("pactl")
    if pactl is not None:
        try:
            pulse_result = subprocess.run(
                [pactl, "list", "short", "sources"],
                capture_output=True,
                text=True,
                check=False,
                close_fds=True,
                timeout=2.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            pulse_result = None
        if pulse_result is not None and pulse_result.returncode == 0:
            pulse_sources = {
                fields[1]
                for line in pulse_result.stdout.splitlines()
                if len(fields := line.split()) >= 2
                and not fields[1].casefold().endswith(".monitor")
            }

    executable = shutil.which("gpu-screen-recorder")
    if executable is None:
        return {}
    try:
        result = subprocess.run(
            [executable, "--list-audio-devices"],
            capture_output=True,
            text=True,
            check=False,
            close_fds=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode != 0:
        return {}

    choices: dict[str, str] = {}
    for line in result.stdout.splitlines():
        source_name, separator, description = line.partition("|")
        source_name = source_name.strip()
        description = description.strip()
        if not separator or not source_name:
            continue
        if source_name == "default_input":
            continue
        device_name = source_name.removeprefix("device:")
        device_description = description or device_name
        if pulse_sources is not None and device_name not in pulse_sources:
            continue
        if (
            source_name == "default_output"
            or device_name.casefold().endswith(".monitor")
            or "monitor" in device_description.casefold()
            or "output" in device_description.casefold()
        ):
            continue
        label = f"Microphone: {device_description}"
        if label in choices:
            label = f"{label} ({device_name})"
        choices[label] = f"device:{device_name}"
    return choices


def _available_clipping_applications() -> tuple[str, ...]:
    executable = shutil.which("gpu-screen-recorder")
    if executable is None:
        return ()
    try:
        result = subprocess.run(
            [executable, "--list-application-audio"],
            capture_output=True,
            text=True,
            check=False,
            close_fds=True,
            timeout=2.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    if result.returncode != 0:
        return ()

    applications = {}
    for line in result.stdout.splitlines():
        name = line.partition("|")[0].strip()
        if name.startswith("app:"):
            name = name.removeprefix("app:").strip()
        if (
            not name
            or len(name) > 200
            or any(character in name for character in "\0\r\n|,")
        ):
            continue
        applications.setdefault(name.casefold(), name)
    return tuple(sorted(applications.values(), key=str.casefold))


def _parse_clipping_app_exclusions(raw_value: str | None) -> tuple[str, ...]:
    if not raw_value:
        return ()
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    values = {}
    for item in parsed:
        if not isinstance(item, str):
            continue
        name = item.strip()
        if (
            not name
            or len(name) > 200
            or any(character in name for character in "\0\r\n|,")
        ):
            continue
        values.setdefault(name.casefold(), name)
    return tuple(values.values())


def _configured_microphone_source(raw_value: str | None) -> str:
    if not raw_value:
        return ""
    for source in (part.strip() for part in raw_value.split("|")):
        if source == "default_input" or source.startswith("device:"):
            return source
    return ""


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
        self.clip_app_vars: dict[str, tk.BooleanVar] = {}

        try:
            self.config_path = configuration_file()
            parsed = dotenv_values(self.config_path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Jarvis Settings", str(exc), parent=self.root)
            parsed = {}
            self.config_path = Path(".env")

        self.original_clip_audio = _configured_microphone_source(
            parsed.get("CLIP_AUDIO")
        )
        self.clip_audio_options = {
            **CLIP_AUDIO_LABEL_TO_VALUE,
            **_available_clipping_microphones(),
        }
        if self.original_clip_audio and self.original_clip_audio not in set(
            self.clip_audio_options.values()
        ):
            self.clip_audio_options[CUSTOM_CLIP_AUDIO_LABEL] = (
                self.original_clip_audio
            )
        self.clip_audio_value_to_label = {
            value: label for label, value in self.clip_audio_options.items()
        }
        self.clip_audio_exclusions = _parse_clipping_app_exclusions(
            parsed.get("CLIP_AUDIO_EXCLUDE_APPS")
        )
        self.clip_audio_app_names = _available_clipping_applications()
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
        voice = ttk.Frame(notebook, padding=12)
        notebook.add(general, text="General")
        notebook.add(applications, text="Applications")
        notebook.add(terminal, text="Terminal safety")
        notebook.add(clips, text="Clipping")
        notebook.add(voice, text="Voice")

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
        self._add_clipping_app_exclusions(clips)
        self._add_fields(voice, VOICE_DEFAULTS, parsed)
        ttk.Label(
            voice,
            text=(
                "Automatic TTS uses CUDA when available. Choose CPU to keep "
                "speech synthesis off the GPU; the CPU thread limit applies "
                "only when synthesis uses the CPU."
            ),
            wraplength=560,
            style="Muted.TLabel",
        ).grid(
            row=len(VOICE_DEFAULTS),
            column=0,
            columnspan=2,
            sticky="w",
            pady=(10, 4),
        )
        ttk.Label(
            voice,
            text=(
                "Recording ends after this much silence, or at the maximum "
                "utterance length. Longer silence gives you more time to pause "
                "between phrases."
            ),
            wraplength=560,
            style="Muted.TLabel",
        ).grid(
            row=len(VOICE_DEFAULTS) + 1,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(4, 0),
        )

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
        labels = {
            "JARVIS_TTS_DEVICE": "Speech synthesis device",
            "JARVIS_TTS_CPU_THREADS": "Speech CPU threads",
            "VOICE_SILENCE_SECONDS": "End recording after silence (seconds)",
            "VOICE_MAX_UTTERANCE_SECONDS": "Maximum utterance (seconds)",
            "CLIP_SYSTEM_AUDIO": "System audio",
            "CLIP_AUDIO": "Microphone",
        }
        for row, (key, default) in enumerate(defaults.items()):
            value = parsed.get(key)
            stored_value = default if value is None else str(value)
            if key in TIER_OVERRIDE_KEYS:
                value = TIER_POLICY_VALUE_TO_LABEL.get(
                    stored_value,
                    TIER_POLICY_VALUE_TO_LABEL[default],
                )
            elif key == "CLIP_AUDIO":
                microphone = _configured_microphone_source(stored_value)
                value = self.clip_audio_value_to_label.get(
                    microphone,
                    NO_MICROPHONE_LABEL,
                )
            else:
                value = stored_value
            variable = tk.StringVar(value=value)
            self.variables[key] = variable
            label_text = TIER_OVERRIDE_LABELS.get(
                key,
                labels.get(key, key.replace("_", " ").title()),
            )
            if key in TIER_OVERRIDE_KEYS:
                label_group = ttk.Frame(parent)
                label_group.grid(
                    row=row,
                    column=0,
                    sticky="w",
                    padx=(0, 12),
                    pady=5,
                )
                ttk.Label(label_group, text=label_text).pack(side="left")
                help_icon = ttk.Label(
                    label_group,
                    text="?",
                    foreground=self.palette["accent"],
                    cursor="question_arrow",
                    takefocus=True,
                    padding=(4, 2),
                )
                help_icon.pack(side="left", padx=(4, 0))
                self._add_hover_tooltip(help_icon, TIER_OVERRIDE_HELP[key])
                ttk.Combobox(
                    parent,
                    textvariable=variable,
                    values=tuple(TIER_POLICY_LABEL_TO_VALUE),
                    state="readonly",
                    width=28,
                ).grid(row=row, column=1, sticky="ew", pady=5)
                continue

            ttk.Label(parent, text=label_text).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=5
            )
            if key == "CLIP_SYSTEM_AUDIO":
                ttk.Checkbutton(
                    parent,
                    text="Enabled",
                    variable=variable,
                    onvalue="true",
                    offvalue="false",
                ).grid(row=row, column=1, sticky="w", pady=5)
            elif key == "CLIP_AUDIO":
                ttk.Combobox(
                    parent,
                    textvariable=variable,
                    values=tuple(self.clip_audio_options),
                    state="readonly",
                ).grid(row=row, column=1, sticky="ew", pady=5)
            elif key == "JARVIS_TTS_DEVICE":
                ttk.Combobox(
                    parent,
                    textvariable=variable,
                    values=("auto", "cpu", "cuda"),
                    state="readonly",
                ).grid(row=row, column=1, sticky="ew", pady=5)
            elif key == "TERMINAL_COMMANDS_ENABLED":
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

    def _add_clipping_app_exclusions(self, parent: ttk.Frame) -> None:
        row = len(CLIP_DEFAULTS)
        parent.rowconfigure(row, weight=1)
        section = ttk.LabelFrame(
            parent,
            text="Application audio exclusions",
            padding=8,
        )
        section.grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(8, 0),
        )
        section.columnconfigure(0, weight=1)
        ttk.Label(
            section,
            text=(
                "Check apps to exclude their audio. With system audio enabled, "
                "any checked app switches capture to per-app audio. App audio "
                "requires PipeWire and may omit desktop sounds not exposed as "
                "app audio. Turn off system audio to record no desktop or app "
                "audio."
            ),
            wraplength=560,
            style="Muted.TLabel",
        ).grid(row=0, column=0, sticky="ew")
        ttk.Button(
            section,
            text="Refresh app list",
            command=self._refresh_clipping_applications,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0))

        list_frame = ttk.Frame(section)
        list_frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(6, 0),
        )
        section.rowconfigure(1, weight=1)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.clip_apps_canvas = tk.Canvas(
            list_frame,
            height=112,
            highlightthickness=0,
            background=self.palette["surface"],
        )
        self.clip_apps_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.clip_apps_canvas.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.clip_apps_canvas.configure(yscrollcommand=scrollbar.set)
        self.clip_apps_inner = ttk.Frame(self.clip_apps_canvas)
        self.clip_apps_window = self.clip_apps_canvas.create_window(
            (0, 0),
            window=self.clip_apps_inner,
            anchor="nw",
        )
        self.clip_apps_inner.bind(
            "<Configure>",
            lambda _event: self.clip_apps_canvas.configure(
                scrollregion=self.clip_apps_canvas.bbox("all")
            ),
        )
        self.clip_apps_canvas.bind(
            "<Configure>",
            lambda event: self.clip_apps_canvas.itemconfigure(
                self.clip_apps_window,
                width=event.width,
            ),
        )
        self._render_clipping_applications()

    def _render_clipping_applications(self) -> None:
        for child in self.clip_apps_inner.winfo_children():
            child.destroy()
        self.clip_app_vars.clear()

        current_names = list(self.clip_audio_app_names)
        current_keys = {name.casefold() for name in current_names}
        stale_exclusions = [
            name
            for name in self.clip_audio_exclusions
            if name.casefold() not in current_keys
        ]
        names = current_names + stale_exclusions
        if not names:
            ttk.Label(
                self.clip_apps_inner,
                text=(
                    "No app audio streams detected. Open an app and start "
                    "audio, then refresh the list."
                ),
                style="Muted.TLabel",
            ).grid(row=0, column=0, sticky="w", padx=4, pady=4)
            return

        excluded = {name.casefold() for name in self.clip_audio_exclusions}
        for app_row, name in enumerate(names):
            variable = tk.BooleanVar(value=name.casefold() in excluded)
            self.clip_app_vars[name] = variable
            label = name
            if name.casefold() not in current_keys:
                label = f"{name} (not currently detected)"
            ttk.Checkbutton(
                self.clip_apps_inner,
                text=label,
                variable=variable,
                onvalue=True,
                offvalue=False,
            ).grid(row=app_row, column=0, sticky="w", padx=4, pady=1)

    def _refresh_clipping_applications(self) -> None:
        self.clip_audio_exclusions = tuple(
            name
            for name, variable in self.clip_app_vars.items()
            if variable.get()
        )
        self.clip_audio_app_names = _available_clipping_applications()
        self._render_clipping_applications()

    def _add_hover_tooltip(self, widget, text: str) -> None:
        popup_window = None

        def hide(_event=None):
            nonlocal popup_window
            if popup_window is not None:
                try:
                    popup_window.destroy()
                except tk.TclError:
                    pass
                popup_window = None

        def show(_event=None):
            nonlocal popup_window
            if popup_window is not None:
                return
            popup_window = tk.Toplevel(self.root)
            popup_window.wm_overrideredirect(True)
            popup_window.configure(background=self.palette["border"])
            ttk_label = tk.Label(
                popup_window,
                text=text,
                justify="left",
                wraplength=360,
                padx=9,
                pady=7,
                background=self.palette["surface_alt"],
                foreground=self.palette["foreground"],
                font=("TkDefaultFont", 10),
            )
            ttk_label.pack(padx=1, pady=1)
            popup_window.update_idletasks()
            x = widget.winfo_rootx() + widget.winfo_width() + 5
            y = widget.winfo_rooty()
            popup_window.wm_geometry(f"+{x}+{y}")

        widget.bind("<Enter>", show)
        widget.bind("<Leave>", hide)
        widget.bind("<FocusIn>", show)
        widget.bind("<FocusOut>", hide)
        widget.bind("<ButtonPress-1>", show)

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
        values["JARVIS_TTS_DEVICE"] = values["JARVIS_TTS_DEVICE"].casefold()
        if values["JARVIS_TTS_DEVICE"] not in {"auto", "cpu", "cuda"}:
            raise ValueError("TTS device must be auto, cpu, or cuda.")
        cpu_threads = int(values["JARVIS_TTS_CPU_THREADS"])
        if not 1 <= cpu_threads <= 32:
            raise ValueError("TTS CPU threads must be between 1 and 32.")
        values["JARVIS_TTS_CPU_THREADS"] = str(cpu_threads)
        for key, minimum, maximum in (
            ("VOICE_SILENCE_SECONDS", 0.3, 5.0),
            ("VOICE_MAX_UTTERANCE_SECONDS", 5.0, 180.0),
        ):
            try:
                number = float(values[key])
            except ValueError as exc:
                raise ValueError(
                    f"{key} must be a number from {minimum} to {maximum}."
                ) from exc
            if not minimum <= number <= maximum:
                raise ValueError(
                    f"{key} must be from {minimum} to {maximum} seconds."
                )
            values[key] = str(number)
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
            policy_value = TIER_POLICY_LABEL_TO_VALUE.get(values[key])
            if policy_value is None:
                raise ValueError(f"Choose a valid approval policy for {key}.")
            values[key] = policy_value

        for key in ("CLIP_DURATION", "CLIP_FPS"):
            number = int(values[key])
            if number < 1:
                raise ValueError(f"{key} must be a positive whole number.")
            values[key] = str(number)
        values["CLIP_SYSTEM_AUDIO"] = values["CLIP_SYSTEM_AUDIO"].casefold()
        if values["CLIP_SYSTEM_AUDIO"] not in {"true", "false"}:
            raise ValueError("System audio setting must be true or false.")
        for key in (
            "CLIP_MONITOR",
            "CLIP_QUALITY",
            "CLIP_CODEC",
            "CLIP_FORMAT",
            "CLIP_DIRECTORY",
        ):
            if not values[key]:
                raise ValueError(f"{key} cannot be empty.")
        selected_clip_audio = values["CLIP_AUDIO"]
        if selected_clip_audio in self.clip_audio_options:
            values["CLIP_AUDIO"] = self.clip_audio_options[selected_clip_audio]
        else:
            raise ValueError("Choose a valid microphone option.")
        values["CLIP_AUDIO_EXCLUDE_APPS"] = json.dumps(
            [
                name
                for name, variable in self.clip_app_vars.items()
                if variable.get()
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
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

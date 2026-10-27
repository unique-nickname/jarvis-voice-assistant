"""Desktop launcher and compact status indicator for Jarvis."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys

from dotenv import dotenv_values

from core.config import PROJECT_ROOT, configuration_file
from jarvis_ui.process_control import stop_existing_jarvis_processes
from jarvis_ui.theme import apply_theme

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox, ttk
except ImportError as exc:
    tk = None
    tkfont = None
    messagebox = None
    ttk = None
    TKINTER_ERROR = exc
else:
    TKINTER_ERROR = None


STATE_PRESENTATION = {
    "starting": ("Starting", "#e8b84a"),
    "wake_word": ("Wake word", "#5887ff"),
    "listening_command": ("Listening", "#44c7d9"),
    "thinking": ("Thinking", "#a978ef"),
    "executing": ("Working", "#ed9b48"),
    "waiting_approval": ("Approval needed", "#ff5252"),
    "speaking": ("Speaking", "#61c784"),
    "follow_up": ("Follow-up", "#44c7d9"),
    "error": ("Attention needed", "#ff5252"),
    "stopped": ("Stopped", "#858b98"),
    "already_running": ("Already running", "#e8b84a"),
    "stopping": ("Stopping", "#e8b84a"),
}
DISPLAY_ENVIRONMENT = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XAUTHORITY",
    "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_DESKTOP",
    "HYPRLAND_INSTANCE_SIGNATURE",
    "DESKTOP_SESSION",
    "HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
)


def _settings_environment() -> dict[str, str]:
    names = (
        *DISPLAY_ENVIRONMENT,
        "PATH",
        "JARVIS_CONFIG_FILE",
    )
    environment = {name: os.environ[name] for name in names if name in os.environ}
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def _configured_topmost() -> bool:
    try:
        values = dotenv_values(configuration_file())
    except (OSError, ValueError):
        return True
    setting = values.get("STATUS_INDICATOR_ALWAYS_ON_TOP", "true")
    return str(setting).strip().casefold() not in {"0", "false", "no", "off"}


def _configured_ui_theme() -> str:
    try:
        values = dotenv_values(configuration_file())
    except (OSError, ValueError):
        return "dark"
    theme = str(values.get("JARVIS_UI_THEME", "dark")).strip().casefold()
    return theme if theme in {"dark", "light"} else "dark"


def _configured_indicator_options() -> dict[str, object]:
    defaults: dict[str, object] = {
        "style": "pill",
        "persistent": True,
        "monitor": "",
        "width": 150,
        "height": 32,
    }
    try:
        values = dotenv_values(configuration_file())
    except (OSError, ValueError):
        return defaults

    style = str(values.get("STATUS_INDICATOR_STYLE", "pill")).strip().casefold()
    defaults["style"] = style if style in {"pill", "dot"} else "pill"
    persistent = str(
        values.get("STATUS_INDICATOR_PERSISTENT", "true")
    ).strip().casefold()
    defaults["persistent"] = persistent not in {"0", "false", "no", "off"}
    defaults["monitor"] = str(
        values.get("STATUS_INDICATOR_MONITOR", "") or ""
    ).strip()

    for key, name, minimum, maximum in (
        ("width", "STATUS_INDICATOR_WIDTH", 140, 480),
        ("height", "STATUS_INDICATOR_HEIGHT", 22, 80),
    ):
        try:
            parsed = int(values.get(name, defaults[key]))
        except (TypeError, ValueError):
            continue
        if minimum <= parsed <= maximum:
            defaults[key] = parsed
    return defaults


def _is_hyprland() -> bool:
    desktop_names = {
        name.strip().casefold()
        for variable in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP")
        for name in os.environ.get(variable, "").split(":")
    }
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) or (
        "hyprland" in desktop_names
    )


def _run_hyprland_dispatch(
    hyprctl: str,
    lua_dispatcher: str,
    environment: dict[str, str],
    *,
    legacy_dispatcher: str | None = None,
) -> tuple[bool, str]:
    command = [hyprctl, "dispatch", lua_dispatcher]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            close_fds=True,
            shell=False,
            env=environment,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        lua_error = str(exc)
    else:
        lua_error = (result.stderr or result.stdout).strip()
        if result.returncode == 0:
            return True, ""

    if legacy_dispatcher is None:
        return False, lua_error

    try:
        legacy_result = subprocess.run(
            [hyprctl, "dispatch", legacy_dispatcher],
            capture_output=True,
            text=True,
            check=False,
            close_fds=True,
            shell=False,
            env=environment,
            timeout=1.5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{lua_error}; legacy dispatcher failed: {exc}"
    if legacy_result.returncode == 0:
        return True, ""
    legacy_error = (legacy_result.stderr or legacy_result.stdout).strip()
    return False, f"{lua_error}; {legacy_error}".strip("; ")


class JarvisLauncher:
    def __init__(self, *, indicator_only: bool = False) -> None:
        self.indicator_only = indicator_only
        self.root = tk.Tk(className="Jarvis")
        self.root.title("Jarvis")
        self.root.geometry("500x410")
        self.root.minsize(430, 360)
        self.root.protocol("WM_DELETE_WINDOW", self._minimize)
        self.palette = apply_theme(self.root, _configured_ui_theme())

        self.process: subprocess.Popen[bytes] | None = None
        self.status_reader: int | None = None
        self.status_buffer = b""
        self.status = "stopped"
        indicator_options = _configured_indicator_options()
        self.indicator_style = str(indicator_options["style"])
        self.indicator_persistent = bool(indicator_options["persistent"])
        self.indicator_monitor = str(indicator_options["monitor"])
        self.indicator_width = int(indicator_options["width"])
        self.indicator_height = int(indicator_options["height"])
        self.hyprland = _is_hyprland()
        self._overlay_pin_target: bool | None = None
        self._overlay_monitor_name: str | None = None
        self._overlay_monitor_initialized = False
        self._hyprland_issue_reported = False
        self.overlay_visible = tk.BooleanVar(value=True)
        self.topmost = tk.BooleanVar(value=_configured_topmost())

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        content = ttk.Frame(self.root, padding=(18, 14))
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(4, weight=1)
        ttk.Label(
            content,
            text="Jarvis",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content,
            text="Voice assistant · Local desktop control",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 12))

        status_row = ttk.Frame(content, padding=(12, 10), style="Card.TFrame")
        status_row.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        status_row.columnconfigure(1, weight=1)
        self.status_canvas = tk.Canvas(
            status_row,
            width=22,
            height=22,
            highlightthickness=0,
            background=self.palette["surface"],
        )
        self.status_canvas.grid(row=0, column=0, padx=(0, 8))
        self.status_circle = self.status_canvas.create_oval(
            3, 3, 19, 19, fill=STATE_PRESENTATION["stopped"][1], outline=""
        )
        self.status_label = ttk.Label(
            status_row,
            text="Stopped",
            style="CardTitle.TLabel",
        )
        self.status_label.grid(row=0, column=1, sticky="w")

        controls = ttk.Frame(content)
        controls.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure((0, 1), weight=1)
        self.start_button = ttk.Button(
            controls,
            text="Start Jarvis",
            command=self.start_assistant,
            style="Accent.TButton",
        )
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=3)
        self.stop_button = ttk.Button(
            controls,
            text="Stop Jarvis",
            command=self.stop_assistant,
            style="Danger.TButton",
            state="disabled",
        )
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=3)
        ttk.Button(
            controls,
            text="Settings",
            command=self.open_settings,
        ).grid(row=1, column=0, sticky="ew", padx=(0, 5), pady=3)
        ttk.Button(
            controls,
            text="Run without UI",
            command=self.start_without_ui,
        ).grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=3)

        preferences = ttk.Frame(content, padding=(12, 10), style="Card.TFrame")
        preferences.grid(row=4, column=0, sticky="new")
        ttk.Checkbutton(
            preferences,
            text="Show the floating status indicator",
            variable=self.overlay_visible,
            command=self._update_overlay_visibility,
            style="Card.TCheckbutton",
        ).grid(row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Checkbutton(
            preferences,
            text="Keep the status indicator on top",
            variable=self.topmost,
            command=self._update_topmost,
            style="Card.TCheckbutton",
        ).grid(row=1, column=0, sticky="w")

        self.overlay = self._create_overlay()
        self._place_overlay()
        self._update_overlay_visibility()
        self.root.after(100, self._poll_status)
        if self.indicator_only:
            self.root.withdraw()
            self.root.after_idle(self.start_assistant)

    def _create_overlay(self) -> tk.Toplevel:
        window = tk.Toplevel(self.root, class_="JarvisStatus")
        window.title("Jarvis Status")
        window.overrideredirect(True)
        window.configure(background="#171a22")
        try:
            window.attributes("-topmost", self.topmost.get())
        except tk.TclError:
            self.topmost.set(False)
        window.bind("<Button-1>", lambda _event: self.show_launcher())
        window.bind("<Button-3>", self._show_overlay_menu)
        if not self.indicator_monitor:
            window.bind("<ButtonPress-1>", self._drag_start, add="+")
            window.bind("<B1-Motion>", self._drag_move)

        if self.indicator_style == "dot":
            width = height = 24
            self.overlay_canvas = tk.Canvas(
                window,
                width=width,
                height=height,
                highlightthickness=0,
                background="#171a22",
            )
            self.overlay_circle = self.overlay_canvas.create_oval(
                5, 5, 19, 19, fill=STATE_PRESENTATION["stopped"][1], outline=""
            )
            self.overlay_label = None
        else:
            font = ("TkDefaultFont", 9)
            self.overlay_font = tkfont.Font(font=font)
            width = self.indicator_width
            height = self.indicator_height
            self.overlay_canvas = tk.Canvas(
                window,
                width=width,
                height=height,
                highlightthickness=0,
                background="#171a22",
            )
            radius = height // 2
            self.overlay_canvas.create_polygon(
                radius, 1,
                width - radius, 1,
                width - 1, radius,
                width - 1, height - radius,
                width - radius, height - 1,
                radius, height - 1,
                1, height - radius,
                1, radius,
                smooth=True,
                splinesteps=24,
                fill="#252b37",
                outline="#303746",
            )
            self.overlay_circle = self.overlay_canvas.create_oval(
                8,
                height // 2 - 5,
                18,
                height // 2 + 5,
                fill=STATE_PRESENTATION["stopped"][1],
                outline="",
            )
            self.overlay_label = self.overlay_canvas.create_text(
                25,
                height / 2,
                text=self._fit_overlay_label("Stopped"),
                anchor="w",
                fill="#f2f3f5",
                font=font,
            )
        self.overlay_canvas.grid(row=0, column=0)
        return window

    def _place_overlay(self) -> None:
        self.root.update_idletasks()
        self.overlay.update_idletasks()
        x = max(
            0,
            self.root.winfo_screenwidth() - self.overlay.winfo_reqwidth() - 16,
        )
        self.overlay.geometry(f"+{x}+40")

    def _fit_overlay_label(self, label: str) -> str:
        available_width = max(1, self.indicator_width - 35)
        if self.overlay_font.measure(label) <= available_width:
            return label
        shortened = label
        while shortened and self.overlay_font.measure(shortened + "…") > available_width:
            shortened = shortened[:-1]
        return shortened + "…"

    def _drag_start(self, event: tk.Event) -> None:
        self._drag_x = event.x_root - self.overlay.winfo_x()
        self._drag_y = event.y_root - self.overlay.winfo_y()

    def _drag_move(self, event: tk.Event) -> None:
        x = event.x_root - getattr(self, "_drag_x", 0)
        y = event.y_root - getattr(self, "_drag_y", 0)
        self.overlay.geometry(f"+{x}+{y}")

    def _show_overlay_menu(self, event: tk.Event) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Open Jarvis", command=self.show_launcher)
        menu.add_command(label="Settings", command=self.open_settings)
        menu.add_separator()
        if self.process is not None and self.process.poll() is None:
            menu.add_command(label="Stop Jarvis", command=self.stop_assistant)
        menu.add_command(label="Hide indicator", command=self._hide_overlay)
        menu.tk_popup(event.x_root, event.y_root)

    def _hide_overlay(self) -> None:
        self.overlay_visible.set(False)
        self._update_overlay_visibility()

    def _update_overlay_visibility(self) -> None:
        if self.overlay_visible.get():
            self._place_overlay()
            self.overlay.deiconify()
            self.overlay.lift()
            if self.hyprland:
                self.root.after(150, self._configure_hyprland_overlay)
        else:
            self.overlay.withdraw()

    def _report_hyprland_issue(self, message: str) -> None:
        if self._hyprland_issue_reported:
            return
        print(f"Jarvis status indicator: {message}", file=sys.stderr, flush=True)
        self._hyprland_issue_reported = True

    def _update_topmost(self) -> None:
        try:
            self.overlay.attributes("-topmost", self.topmost.get())
        except tk.TclError:
            self.topmost.set(False)
            messagebox.showwarning(
                "Topmost setting unavailable",
                "This window system does not support the Tkinter topmost option.",
                parent=self.root,
            )
            return
        try:
            from jarvis_ui.settings import save_configuration

            save_configuration({
                "STATUS_INDICATOR_ALWAYS_ON_TOP": (
                    "true" if self.topmost.get() else "false"
                ),
            })
        except (OSError, ValueError) as exc:
            messagebox.showerror("Jarvis Settings", str(exc), parent=self.root)

    def _configure_hyprland_overlay(self, attempts: int = 40) -> None:
        if not self.overlay_visible.get() or not self.hyprland:
            return
        hyprctl = shutil.which("hyprctl")
        if not hyprctl:
            self._report_hyprland_issue("hyprctl was not found; compositor settings were skipped.")
            return
        environment = {
            key: os.environ[key]
            for key in DISPLAY_ENVIRONMENT
            if key in os.environ
        }
        try:
            result = subprocess.run(
                [hyprctl, "-j", "clients"],
                capture_output=True,
                text=True,
                check=False,
                close_fds=True,
                shell=False,
                env=environment,
                timeout=1.5,
            )
            clients = json.loads(result.stdout) if result.returncode == 0 else []
            clients_error = (
                (result.stderr or result.stdout).strip()
                if result.returncode != 0
                else ""
            )
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            clients = []
            clients_error = "could not query Hyprland clients"

        monitors = []
        try:
            result = subprocess.run(
                [hyprctl, "-j", "monitors"],
                capture_output=True,
                text=True,
                check=False,
                close_fds=True,
                shell=False,
                env=environment,
                timeout=1.5,
            )
            monitors = json.loads(result.stdout) if result.returncode == 0 else []
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            monitors = []

        found_indicator = False
        for client in clients if isinstance(clients, list) else []:
            if not isinstance(client, dict):
                continue
            titles = (
                str(client.get("title", "")).casefold(),
                str(client.get("initialTitle", "")).casefold(),
            )
            classes = (
                str(client.get("class", "")).casefold(),
                str(client.get("initialClass", "")).casefold(),
            )
            if not (
                any("jarvis status" in title for title in titles)
                or any(value == "jarvisstatus" for value in classes)
            ):
                continue
            address = client.get("address")
            if not isinstance(address, str):
                continue
            found_indicator = True
            if client.get("floating") is not True:
                try:
                    from terminal.approval_ui import _request_floating

                    floated = _request_floating(hyprctl, address)
                    if not floated and attempts == 1:
                        self._report_hyprland_issue(
                            "Hyprland refused to float the status window."
                        )
                except (OSError, subprocess.TimeoutExpired):
                    if attempts == 1:
                        self._report_hyprland_issue(
                            "could not send the float request to Hyprland."
                        )
                    pass
                break

            pin_state = client.get("pinned")
            desired_pin = self.indicator_persistent
            if isinstance(pin_state, bool):
                if pin_state == desired_pin:
                    self._overlay_pin_target = None
                should_dispatch_pin = (
                    pin_state != desired_pin
                    and self._overlay_pin_target is not desired_pin
                )
            else:
                should_dispatch_pin = (
                    desired_pin and self._overlay_pin_target is None
                )
            if should_dispatch_pin:
                self._overlay_pin_target = desired_pin
                selector = json.dumps(f"address:{address}")
                pin_success, pin_error = _run_hyprland_dispatch(
                    hyprctl,
                    f"hl.dsp.window.pin({{ window = {selector} }})",
                    environment,
                    legacy_dispatcher=f"pin address:{address}",
                )
                if not pin_success:
                    self._overlay_pin_target = None
                    if attempts == 1:
                        self._report_hyprland_issue(
                            "Hyprland rejected the workspace pin request. "
                            + pin_error[:180]
                        )
                break

            if self.indicator_monitor:
                target_monitor = next(
                    (
                        monitor
                        for monitor in (monitors if isinstance(monitors, list) else [])
                        if isinstance(monitor, dict)
                        and monitor.get("name") == self.indicator_monitor
                    ),
                    None,
                )
            else:
                target_monitor = next(
                    (
                        monitor
                        for monitor in (monitors if isinstance(monitors, list) else [])
                        if isinstance(monitor, dict)
                        and monitor.get("name") == self._overlay_monitor_name
                    ),
                    None,
                )
                if target_monitor is None:
                    current_monitor_id = client.get("monitor")
                    target_monitor = next(
                        (
                            monitor
                            for monitor in (monitors if isinstance(monitors, list) else [])
                            if isinstance(monitor, dict)
                            and monitor.get("id") == current_monitor_id
                        ),
                        None,
                    )
                if target_monitor is None:
                    target_monitor = next(
                        (
                            monitor
                            for monitor in (monitors if isinstance(monitors, list) else [])
                            if isinstance(monitor, dict)
                            and monitor.get("focused") is True
                        ),
                        None,
                    )
                if target_monitor is None:
                    target_monitor = next(
                        (
                            monitor
                            for monitor in (monitors if isinstance(monitors, list) else [])
                            if isinstance(monitor, dict)
                        ),
                        None,
                    )
                if (
                    target_monitor is not None
                    and isinstance(target_monitor.get("name"), str)
                ):
                    self._overlay_monitor_name = target_monitor["name"]

            if target_monitor is not None:
                should_position = bool(self.indicator_monitor) or not (
                    self._overlay_monitor_initialized
                )
                if should_position:
                    position = None
                    try:
                        monitor_x = float(target_monitor["x"])
                        monitor_y = float(target_monitor["y"])
                        monitor_width = float(target_monitor["width"])
                        scale = max(0.1, float(target_monitor.get("scale", 1)))
                        size = client.get("size", [])
                        window_width = (
                            float(size[0])
                            if len(size) > 0
                            else self.indicator_width
                        )
                        logical_width = monitor_width / scale
                        x = round(monitor_x + logical_width - window_width - 16)
                        y = round(monitor_y + 40)
                        at = client.get("at", [])
                        position = (x, y)
                        same_monitor = (
                            client.get("monitor") == target_monitor.get("id")
                        )
                        already_positioned = (
                            same_monitor
                            and len(at) >= 2
                            and abs(float(at[0]) - x) <= 2
                            and abs(float(at[1]) - y) <= 2
                        )
                    except (KeyError, TypeError, ValueError, OverflowError):
                        already_positioned = False
                    if position is not None and not already_positioned:
                        selector = json.dumps(f"address:{address}")
                        move_dispatcher = (
                            "hl.dsp.window.move({ window = "
                            f"{selector}, x = {x}, y = {y}, relative = false }})"
                        )
                        move_success, move_error = _run_hyprland_dispatch(
                            hyprctl,
                            move_dispatcher,
                            environment,
                            legacy_dispatcher=(
                                f"movewindowpixel exact {x} {y},address:{address}"
                            ),
                        )
                        if not move_success:
                            if attempts == 1:
                                self._report_hyprland_issue(
                                    "Hyprland rejected the monitor placement request. "
                                    + move_error[:180]
                                )
                            break
                        self._overlay_monitor_initialized = True
                        break
                    self._overlay_monitor_initialized = True
            elif self.indicator_monitor:
                # A configured output can appear after the indicator starts.
                if attempts == 1:
                    self._report_hyprland_issue(
                        f"configured monitor {self.indicator_monitor!r} is not active."
                    )
                break
            elif not isinstance(monitors, list) or not monitors:
                break
            if self.indicator_monitor and target_monitor is None:
                break
            return
        if attempts > 1:
            self.root.after(150, self._configure_hyprland_overlay, attempts - 1)
        elif not found_indicator:
            detail = f" ({clients_error[:180]})" if clients_error else ""
            self._report_hyprland_issue(
                "could not find the Jarvis Status window in Hyprland clients" + detail
            )

    def _set_status(self, state: str) -> None:
        if state not in STATE_PRESENTATION:
            return
        self.status = state
        label, color = STATE_PRESENTATION[state]
        self.status_label.configure(text=label)
        self.status_canvas.itemconfigure(self.status_circle, fill=color)
        if self.overlay_label is not None:
            self.overlay_canvas.itemconfigure(
                self.overlay_label,
                text=self._fit_overlay_label(label),
            )
        self.overlay_canvas.itemconfigure(self.overlay_circle, fill=color)
        active = self.process is not None and self.process.poll() is None
        self.start_button.configure(state="disabled" if active else "normal")
        self.stop_button.configure(state="normal" if active else "disabled")

    def start_assistant(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        read_fd, write_fd = os.pipe()
        environment = os.environ.copy()
        environment["JARVIS_STATUS_FD"] = str(write_fd)
        environment.pop("JARVIS_STATUS_OUTPUT", None)
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-u", "-m", "voice.assistant_loop"],
                cwd=PROJECT_ROOT,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                pass_fds=(write_fd,),
                start_new_session=True,
            )
        except OSError as exc:
            os.close(read_fd)
            os.close(write_fd)
            self._set_status("error")
            messagebox.showerror("Could not start Jarvis", str(exc), parent=self.root)
            return
        os.close(write_fd)
        os.set_blocking(read_fd, False)
        self.status_reader = read_fd
        self._set_status("starting")
        self._update_overlay_visibility()

    def stop_assistant(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self._set_status("stopping")
        try:
            self.process.send_signal(signal.SIGINT)
        except OSError as exc:
            messagebox.showerror("Could not stop Jarvis", str(exc), parent=self.root)

    def open_settings(self) -> None:
        try:
            subprocess.Popen(
                [sys.executable, "-m", "jarvis_ui.settings"],
                cwd=PROJECT_ROOT,
                env=_settings_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
        except OSError as exc:
            messagebox.showerror("Could not open settings", str(exc), parent=self.root)

    def start_without_ui(self) -> None:
        if self.process is not None and self.process.poll() is None:
            messagebox.showinfo(
                "Jarvis is running",
                "Stop the current assistant before switching to headless mode.",
                parent=self.root,
            )
            return
        environment = os.environ.copy()
        environment.pop("JARVIS_STATUS_FD", None)
        environment.pop("JARVIS_STATUS_OUTPUT", None)
        os.chdir(PROJECT_ROOT)
        os.execve(
            sys.executable,
            [sys.executable, "-u", "-m", "voice.assistant_loop"],
            environment,
        )

    def _poll_status(self) -> None:
        if self.status_reader is not None:
            try:
                chunk = os.read(self.status_reader, 4096)
            except BlockingIOError:
                chunk = None
            except OSError:
                chunk = b""
            if chunk:
                self.status_buffer += chunk
                while b"\n" in self.status_buffer:
                    line, self.status_buffer = self.status_buffer.split(b"\n", 1)
                    prefix = b"JARVIS_STATUS="
                    if line.startswith(prefix):
                        state = line[len(prefix):].decode("ascii", errors="ignore")
                        self._set_status(state)
            elif chunk == b"":
                os.close(self.status_reader)
                self.status_reader = None

        if self.process is not None and self.process.poll() is not None:
            exit_code = self.process.returncode
            if self.status == "already_running":
                final_state = "already_running"
            elif exit_code == 0:
                final_state = "stopped"
            else:
                final_state = "error"
            if self.status_reader is not None:
                try:
                    os.close(self.status_reader)
                except OSError:
                    pass
                self.status_reader = None
            self.process = None
            self._set_status(final_state)

        self.root.after(100, self._poll_status)

    def show_launcher(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _minimize(self) -> None:
        if self.indicator_only:
            self.root.withdraw()
        elif self.process is not None and self.process.poll() is None:
            self.root.iconify()
        else:
            self.root.destroy()

    def _stop_assistant_for_exit(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            try:
                process.send_signal(signal.SIGINT)
            except OSError:
                pass
            try:
                process.wait(timeout=15)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                try:
                    process.terminate()
                except OSError:
                    pass
                try:
                    process.wait(timeout=2)
                except (subprocess.TimeoutExpired, KeyboardInterrupt):
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=2)
                    except (subprocess.TimeoutExpired, KeyboardInterrupt):
                        pass

        if self.status_reader is not None:
            try:
                os.close(self.status_reader)
            except OSError:
                pass
            self.status_reader = None
        self.process = None

    def run(self) -> None:
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop_assistant_for_exit()
            try:
                self.root.destroy()
            except tk.TclError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch Jarvis with a desktop UI.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--headless",
        action="store_true",
        help="replace the launcher with the voice assistant in the current terminal",
    )
    modes.add_argument(
        "--indicator-only",
        action="store_true",
        help="start Jarvis with the floating status indicator and hide the launcher",
    )
    modes.add_argument(
        "--waybar-status",
        action="store_true",
        help="print the current runtime state as Waybar custom-module JSON",
    )
    modes.add_argument(
        "--stop",
        action="store_true",
        help="stop other Jarvis processes from this checkout and exit",
    )
    parser.add_argument(
        "--kill-existing",
        action="store_true",
        help="stop other Jarvis processes from this checkout before launching",
    )
    arguments = parser.parse_args()
    if arguments.stop and arguments.kill_existing:
        parser.error("--stop cannot be combined with --kill-existing")
    if arguments.waybar_status:
        if arguments.kill_existing:
            parser.error("--waybar-status cannot be combined with --kill-existing")
        from jarvis_ui.waybar_status import main as waybar_status_main

        waybar_status_main()
        return
    if arguments.stop:
        stopped_count, survivors = stop_existing_jarvis_processes()
        if stopped_count:
            print(f"Stopped {stopped_count} existing Jarvis process(es).")
        else:
            print("No other Jarvis processes from this checkout are running.")
        if survivors:
            listed_pids = ", ".join(str(pid) for pid in survivors)
            raise SystemExit(
                "Could not stop all existing Jarvis processes; still running: "
                f"{listed_pids}"
            )
        return
    if arguments.kill_existing:
        stopped_count, survivors = stop_existing_jarvis_processes()
        if stopped_count:
            print(f"Stopped {stopped_count} existing Jarvis process(es).")
        else:
            print("No other Jarvis processes from this checkout are running.")
        if survivors:
            listed_pids = ", ".join(str(pid) for pid in survivors)
            raise SystemExit(
                "Could not stop all existing Jarvis processes; still running: "
                f"{listed_pids}"
            )
    if arguments.headless:
        environment = os.environ.copy()
        environment.pop("JARVIS_STATUS_FD", None)
        environment.pop("JARVIS_STATUS_OUTPUT", None)
        os.chdir(PROJECT_ROOT)
        os.execve(
            sys.executable,
            [sys.executable, "-u", "-m", "voice.assistant_loop"],
            environment,
        )
    if tk is None:
        raise SystemExit(
            "The desktop UI needs Tkinter and the native Tk runtime. "
            "On Arch Linux, install the tk package."
        ) from None
    try:
        JarvisLauncher(indicator_only=arguments.indicator_only).run()
    except tk.TclError as exc:
        raise SystemExit(f"Could not connect to the desktop display: {exc}") from None


if __name__ == "__main__":
    main()

"""Shared light and dark styling for Jarvis's Tkinter windows."""

from __future__ import annotations

THEMES = {
    "dark": {
        "background": "#11151d",
        "surface": "#1b222d",
        "surface_alt": "#263140",
        "foreground": "#edf2f7",
        "muted": "#a8b3c2",
        "accent": "#829cff",
        "accent_active": "#a0b3ff",
        "danger": "#e36b72",
        "danger_active": "#f08086",
        "warning": "#f0c674",
        "border": "#354153",
        "selection": "#344b78",
    },
    "light": {
        "background": "#f2f4f8",
        "surface": "#ffffff",
        "surface_alt": "#e6eaf1",
        "foreground": "#202633",
        "muted": "#596579",
        "accent": "#4268d5",
        "accent_active": "#3155bc",
        "danger": "#c74650",
        "danger_active": "#aa303a",
        "warning": "#8a4f00",
        "border": "#c9d0dc",
        "selection": "#cbd8fb",
    },
}


def apply_theme(root, mode: str = "dark") -> dict[str, str]:
    """Apply a consistent ttk palette and return colors for classic Tk widgets."""
    from tkinter import ttk

    palette = THEMES.get(mode.casefold(), THEMES["dark"])
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    root.configure(background=palette["background"])

    style.configure(
        ".",
        background=palette["background"],
        foreground=palette["foreground"],
        bordercolor=palette["border"],
        lightcolor=palette["border"],
        darkcolor=palette["background"],
        focuscolor=palette["accent"],
        font=("TkDefaultFont", 10),
    )
    style.configure("TFrame", background=palette["background"])
    style.configure("Card.TFrame", background=palette["surface"])
    style.configure(
        "TLabel",
        background=palette["background"],
        foreground=palette["foreground"],
    )
    style.configure(
        "Muted.TLabel",
        background=palette["background"],
        foreground=palette["muted"],
    )
    style.configure(
        "Warning.TLabel",
        background=palette["background"],
        foreground=palette["warning"],
    )
    style.configure(
        "Section.TLabel",
        background=palette["background"],
        foreground=palette["foreground"],
        font=("TkDefaultFont", 12, "bold"),
    )
    style.configure(
        "Header.TLabel",
        background=palette["background"],
        foreground=palette["foreground"],
        font=("TkDefaultFont", 20, "bold"),
    )
    style.configure(
        "CardTitle.TLabel",
        background=palette["surface"],
        foreground=palette["foreground"],
        font=("TkDefaultFont", 11, "bold"),
    )
    style.configure(
        "Card.TLabel",
        background=palette["surface"],
        foreground=palette["foreground"],
    )
    style.configure(
        "TButton",
        padding=(12, 8),
        background=palette["surface_alt"],
        foreground=palette["foreground"],
        borderwidth=0,
        focusthickness=2,
        focuscolor=palette["accent"],
    )
    style.map(
        "TButton",
        background=[
            ("disabled", palette["surface"]),
            ("active", palette["border"]),
        ],
        foreground=[("disabled", palette["muted"])],
    )
    style.configure(
        "Accent.TButton",
        background=palette["accent"],
        foreground="#ffffff",
        font=("TkDefaultFont", 10, "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("active", palette["accent_active"]),
            ("disabled", palette["surface_alt"]),
        ],
        foreground=[("disabled", palette["muted"])],
    )
    style.configure(
        "Danger.TButton",
        background=palette["danger"],
        foreground="#ffffff",
        font=("TkDefaultFont", 10, "bold"),
    )
    style.map("Danger.TButton", background=[("active", palette["danger_active"])])
    style.configure(
        "TCheckbutton",
        background=palette["background"],
        foreground=palette["foreground"],
    )
    style.configure(
        "Card.TCheckbutton",
        background=palette["surface"],
        foreground=palette["foreground"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", palette["background"])],
        foreground=[("disabled", palette["muted"])],
    )
    style.map(
        "Card.TCheckbutton",
        background=[("active", palette["surface"])],
        foreground=[("disabled", palette["muted"])],
    )
    style.configure(
        "TEntry",
        fieldbackground=palette["surface"],
        foreground=palette["foreground"],
        insertcolor=palette["foreground"],
        bordercolor=palette["border"],
        padding=6,
    )
    style.configure(
        "TCombobox",
        fieldbackground=palette["surface"],
        foreground=palette["foreground"],
        arrowcolor=palette["foreground"],
        padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette["surface"])],
        foreground=[("readonly", palette["foreground"])],
    )
    style.configure("TNotebook", background=palette["background"], borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=palette["surface_alt"],
        foreground=palette["muted"],
        padding=(13, 8),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", palette["surface"])],
        foreground=[("selected", palette["foreground"])],
    )
    style.configure("Vertical.TScrollbar", background=palette["surface_alt"])
    return palette

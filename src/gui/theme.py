"""Visual theme and ttk styling for the Moment GUI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class Colors:
    """Soft, friendly palette."""

    BACKGROUND = "#f3f4f8"
    SURFACE = "#ffffff"
    SURFACE_ALT = "#eef0f6"
    TEXT = "#1f2937"
    TEXT_MUTED = "#6b7280"
    ACCENT = "#6366f1"
    ACCENT_DARK = "#4f46e5"
    BORDER = "#dfe3ec"
    PREVIEW_BG = "#1a1b26"
    PREVIEW_BORDER = "#2d3142"
    STATUS_BG = "#e9ebf2"


class Fonts:
    """Typography used across the app."""

    FAMILY = "Segoe UI"
    BODY = (FAMILY, 10)
    BODY_BOLD = (FAMILY, 10, "bold")
    HEADING = (FAMILY, 11, "bold")
    TITLE = (FAMILY, 13, "bold")
    SMALL = (FAMILY, 9)


class Spacing:
    """Consistent padding and gaps."""

    WINDOW = 16
    SECTION = 12
    DIALOG = 20
    CONTROL_GAP = 8
    BUTTON_X = 12
    BUTTON_Y = 7


def apply_theme(root: tk.Misc) -> ttk.Style:
    """Apply the Moment theme and return the configured style."""
    style = ttk.Style(root)

    for theme_name in ("clam", "vista", "default"):
        try:
            style.theme_use(theme_name)
            break
        except tk.TclError:
            continue

    root.configure(bg=Colors.BACKGROUND)

    style.configure(".", background=Colors.BACKGROUND, foreground=Colors.TEXT, font=Fonts.BODY)
    style.configure("TFrame", background=Colors.BACKGROUND)
    style.configure("Surface.TFrame", background=Colors.SURFACE)
    style.configure("Status.TFrame", background=Colors.STATUS_BG)

    style.configure(
        "TLabelframe",
        background=Colors.BACKGROUND,
        borderwidth=1,
        relief="flat",
    )
    style.configure(
        "TLabelframe.Label",
        background=Colors.BACKGROUND,
        foreground=Colors.TEXT,
        font=Fonts.HEADING,
        padding=(4, 0, 4, 6),
    )
    style.configure(
        "Card.TLabelframe",
        background=Colors.SURFACE,
        bordercolor=Colors.BORDER,
        lightcolor=Colors.BORDER,
        darkcolor=Colors.BORDER,
    )
    style.configure(
        "Card.TLabelframe.Label",
        background=Colors.SURFACE,
        foreground=Colors.TEXT,
        font=Fonts.HEADING,
    )

    style.configure(
        "TButton",
        padding=(Spacing.BUTTON_X, Spacing.BUTTON_Y),
        font=Fonts.BODY,
    )
    style.configure(
        "Accent.TButton",
        padding=(Spacing.BUTTON_X + 2, Spacing.BUTTON_Y + 1),
        font=Fonts.BODY_BOLD,
        background=Colors.ACCENT,
        foreground="#ffffff",
        borderwidth=0,
        focusthickness=0,
    )
    style.map(
        "Accent.TButton",
        background=[("active", Colors.ACCENT_DARK), ("disabled", Colors.BORDER)],
        foreground=[("disabled", Colors.TEXT_MUTED)],
    )

    style.configure(
        "TEntry",
        padding=(8, 6),
        fieldbackground=Colors.SURFACE,
        bordercolor=Colors.BORDER,
        lightcolor=Colors.BORDER,
        darkcolor=Colors.BORDER,
    )
    style.configure(
        "TCombobox",
        padding=(8, 6),
        fieldbackground=Colors.SURFACE,
    )
    style.configure(
        "Treeview",
        background=Colors.SURFACE,
        fieldbackground=Colors.SURFACE,
        foreground=Colors.TEXT,
        rowheight=30,
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        background=Colors.SURFACE_ALT,
        foreground=Colors.TEXT,
        font=Fonts.BODY_BOLD,
        padding=(8, 6),
    )
    style.map("Treeview", background=[("selected", Colors.ACCENT)], foreground=[("selected", "#ffffff")])

    style.configure("Muted.TLabel", foreground=Colors.TEXT_MUTED, background=Colors.BACKGROUND)
    style.configure("Title.TLabel", font=Fonts.TITLE, background=Colors.SURFACE)
    style.configure("MutedSurface.TLabel", foreground=Colors.TEXT_MUTED, background=Colors.SURFACE)

    style.configure("Horizontal.TScale", background=Colors.BACKGROUND)

    return style

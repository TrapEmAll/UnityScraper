"""Shared Visual Studio 2010-inspired desktop theme."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from platform_support import desktop_font_family


@dataclass(frozen=True)
class Palette:
    window: str = "#1E1E1E"
    chrome: str = "#2D2D30"
    panel: str = "#252526"
    panel_alt: str = "#333337"
    field: str = "#1B1B1C"
    border: str = "#3F3F46"
    border_hot: str = "#007ACC"
    accent: str = "#007ACC"
    accent_hot: str = "#1C97EA"
    selection: str = "#094771"
    text: str = "#F1F1F1"
    muted: str = "#B8B8B8"
    disabled: str = "#777777"
    success: str = "#6A9955"
    warning: str = "#DCDCAA"
    danger: str = "#F14C4C"


PALETTE = Palette()
UI_FONT = desktop_font_family()
MONO_FONT = "Consolas"


def apply_vs2010_theme(
    root: tk.Misc,
    *,
    high_contrast: bool = False,
    large_text: bool = False,
) -> ttk.Style:
    """Apply one compact, square-edged theme to every ttk workspace."""
    palette = PALETTE
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    font_size = 11 if large_text else 9
    row_height = 30 if large_text else 23
    root.configure(background=palette.window)
    style.configure(
        ".",
        background=palette.panel,
        foreground=palette.text,
        fieldbackground=palette.field,
        bordercolor=palette.border,
        darkcolor=palette.border,
        lightcolor=palette.border,
        troughcolor=palette.window,
        selectbackground=palette.selection,
        selectforeground=palette.text,
        insertcolor=palette.text,
        font=(UI_FONT, font_size),
    )
    style.configure("TFrame", background=palette.panel)
    style.configure("Content.TFrame", background=palette.panel)
    style.configure("Sidebar.TFrame", background=palette.chrome)
    style.configure("Toolbar.TFrame", background=palette.chrome, relief="flat")
    style.configure("Statusbar.TFrame", background=palette.accent)
    style.configure("TLabel", background=palette.panel, foreground=palette.text)
    style.configure("Toolbar.TLabel", background=palette.chrome, foreground=palette.muted)
    style.configure("Statusbar.TLabel", background=palette.accent, foreground="#FFFFFF")
    style.configure(
        "Brand.TLabel", background=palette.chrome, foreground=palette.text,
        font=(UI_FONT, 14, "bold"),
    )
    style.configure(
        "AccentBrand.TLabel", background=palette.chrome, foreground=palette.accent_hot,
        font=(UI_FONT, 9),
    )
    style.configure(
        "Header.TLabel", background=palette.panel, foreground=palette.text,
        font=(UI_FONT, 18, "bold"),
    )
    style.configure(
        "Subheader.TLabel", background=palette.panel, foreground=palette.muted,
        font=(UI_FONT, font_size),
    )
    style.configure(
        "Metric.TLabel", background=palette.panel_alt, foreground=palette.accent_hot,
        font=(UI_FONT, 17, "bold"),
    )
    style.configure(
        "CardTitle.TLabel", background=palette.panel, foreground=palette.text,
        font=(UI_FONT, font_size, "bold"),
    )
    style.configure("StatusDownloaded.TLabel", foreground=palette.success)
    style.configure("StatusFailed.TLabel", foreground=palette.danger)
    style.configure("StatusPending.TLabel", foreground=palette.warning)
    style.configure("Title.TLabel", font=(UI_FONT, 16, "bold"))
    style.configure("Subtitle.TLabel", foreground=palette.muted)
    style.configure("Success.TLabel", foreground=palette.success)
    style.configure("Error.TLabel", foreground=palette.danger)

    style.configure(
        "TButton", background=palette.panel_alt, foreground=palette.text,
        bordercolor=palette.border, padding=(9, 5), borderwidth=1, relief="flat",
    )
    style.map(
        "TButton",
        background=[("pressed", palette.selection), ("active", "#3E3E42")],
        bordercolor=[("focus", palette.border_hot), ("active", "#5A5A60")],
        foreground=[("disabled", palette.disabled)],
    )
    style.configure(
        "Nav.TButton", anchor=tk.W, background=palette.chrome, foreground=palette.muted,
        bordercolor=palette.chrome, padding=(12, 7), relief="flat",
    )
    style.map(
        "Nav.TButton",
        background=[("pressed", palette.selection), ("active", "#3E3E42")],
        foreground=[("pressed", "#FFFFFF"), ("active", "#FFFFFF")],
        bordercolor=[("focus", palette.border_hot)],
    )
    style.configure(
        "Accent.TButton", background=palette.accent, foreground="#FFFFFF",
        bordercolor=palette.accent_hot,
    )
    style.map("Accent.TButton", background=[("active", palette.accent_hot)])
    style.configure(
        "Tool.TButton", background=palette.chrome, foreground=palette.text,
        bordercolor=palette.border, padding=(7, 4),
    )

    style.configure(
        "TLabelframe", background=palette.panel, foreground=palette.text,
        bordercolor=palette.border, relief="solid", borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label", background=palette.panel, foreground=palette.muted,
        font=(UI_FONT, font_size, "bold"),
    )
    for widget in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            widget, fieldbackground=palette.field, foreground=palette.text,
            bordercolor=palette.border, arrowcolor=palette.muted, padding=5,
        )
        style.map(widget, bordercolor=[("focus", palette.border_hot)])
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", palette.field)],
        foreground=[("readonly", palette.text)],
        selectbackground=[("readonly", palette.field)],
        selectforeground=[("readonly", palette.text)],
    )
    style.configure(
        "Treeview", background=palette.field, fieldbackground=palette.field,
        foreground=palette.text, rowheight=row_height, bordercolor=palette.border,
        relief="flat",
    )
    style.map(
        "Treeview", background=[("selected", palette.selection)],
        foreground=[("selected", "#FFFFFF")],
    )
    style.configure(
        "Treeview.Heading", background=palette.chrome, foreground=palette.text,
        bordercolor=palette.border, relief="raised", padding=(6, 4),
        font=(UI_FONT, font_size, "bold"),
    )
    style.map("Treeview.Heading", background=[("active", "#3E3E42")])
    style.configure("TNotebook", background=palette.chrome, bordercolor=palette.border)
    style.configure(
        "TNotebook.Tab", background=palette.chrome, foreground=palette.muted,
        bordercolor=palette.border, padding=(11, 6),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", palette.panel), ("active", "#3E3E42")],
        foreground=[("selected", "#FFFFFF"), ("active", "#FFFFFF")],
        bordercolor=[("selected", palette.accent)],
    )
    style.configure(
        "Vertical.TScrollbar", background=palette.chrome, troughcolor=palette.window,
        arrowcolor=palette.muted, bordercolor=palette.border,
    )
    style.configure("TCheckbutton", background=palette.panel, foreground=palette.text)
    style.configure("TRadiobutton", background=palette.panel, foreground=palette.text)
    style.configure(
        "Horizontal.TProgressbar", background=palette.accent,
        troughcolor=palette.field, bordercolor=palette.border,
    )

    if high_contrast:
        style.configure(
            ".", background="#000000", foreground="#FFFFFF", fieldbackground="#000000",
            bordercolor="#FFFFFF", selectbackground="#FFFFFF", selectforeground="#000000",
        )
        for name in ("TFrame", "Content.TFrame", "Sidebar.TFrame", "Toolbar.TFrame",
                     "TLabel", "Toolbar.TLabel", "TLabelframe", "TLabelframe.Label"):
            style.configure(name, background="#000000", foreground="#FFFFFF")
        style.configure("Treeview", background="#000000", fieldbackground="#000000")
        style.configure("Treeview.Heading", background="#000000", foreground="#FFFFFF")
        style.configure("TNotebook.Tab", background="#000000", foreground="#FFFFFF")
    return style

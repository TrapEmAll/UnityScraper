"""Shared desktop theme: dark, light, and high-contrast palettes with accent colors."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, fields
from tkinter import ttk

from platform_support import desktop_font_family


@dataclass
class Palette:
    """Color tokens. Mutated in place by ``set_theme`` so imported references stay current."""

    window: str = ""
    chrome: str = ""
    panel: str = ""
    panel_alt: str = ""
    hover: str = ""
    field: str = ""
    border: str = ""
    border_hot: str = ""
    accent: str = ""
    accent_hot: str = ""
    on_accent: str = ""
    selection: str = ""
    selection_text: str = ""
    text: str = ""
    muted: str = ""
    disabled: str = ""
    success: str = ""
    warning: str = ""
    danger: str = ""
    info: str = ""


THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "window": "#0F1217", "chrome": "#0A0C10", "panel": "#0F1217",
        "panel_alt": "#171B22", "hover": "#1D222B", "field": "#0A0C10",
        "border": "#252B36", "on_accent": "#0A0C10", "selection_text": "#FFFFFF",
        "text": "#E8EAF0", "muted": "#8C93A3", "disabled": "#555C69",
        "success": "#3FB950", "warning": "#D29922", "danger": "#F85149", "info": "#58A6FF",
    },
    "light": {
        "window": "#F5F6F8", "chrome": "#E9ECF0", "panel": "#F5F6F8",
        "panel_alt": "#FFFFFF", "hover": "#E1E5EB", "field": "#FFFFFF",
        "border": "#D0D5DD", "on_accent": "#FFFFFF", "selection_text": "#1A1D24",
        "text": "#1A1D24", "muted": "#5F6675", "disabled": "#A0A6B1",
        "success": "#1A7F37", "warning": "#9A6700", "danger": "#CF222E", "info": "#0969DA",
    },
    "high_contrast": {
        "window": "#000000", "chrome": "#000000", "panel": "#000000",
        "panel_alt": "#000000", "hover": "#1A1A1A", "field": "#000000",
        "border": "#FFFFFF", "on_accent": "#000000", "selection_text": "#000000",
        "text": "#FFFFFF", "muted": "#FFFFFF", "disabled": "#BFBFBF",
        "success": "#00FF00", "warning": "#FFFF00", "danger": "#FF4040", "info": "#00FFFF",
    },
}

# (dark-theme shade, light-theme shade); high contrast always uses yellow.
ACCENTS: dict[str, tuple[str, str]] = {
    "green": ("#3FB950", "#1F883D"),
    "blue": ("#4C9AFF", "#0969DA"),
    "purple": ("#A371F7", "#8250DF"),
    "orange": ("#F0883E", "#BC4C00"),
    "pink": ("#DB61A2", "#BF3989"),
}
THEME_LABELS = {"dark": "Dark", "light": "Light", "high_contrast": "High contrast"}
DEFAULT_THEME = "dark"
DEFAULT_ACCENT = "green"

PALETTE = Palette()
UI_FONT = desktop_font_family()
MONO_FONT = "Consolas"
_SIZES = {"small": 9, "base": 10, "medium": 12, "large": 15, "title": 20, "metric": 24}
_LARGE_TEXT_SIZES = {"small": 11, "base": 12, "medium": 14, "large": 17, "title": 23, "metric": 27}
_active_sizes = dict(_SIZES)


def mix(first: str, second: str, amount: float) -> str:
    """Blend two ``#RRGGBB`` colors; ``amount`` is the share of ``first``."""
    a = [int(first[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(second[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02X}" for x, y in zip(a, b))


def set_theme(theme: str = DEFAULT_THEME, accent: str = DEFAULT_ACCENT) -> None:
    """Load a theme into ``PALETTE``. Unknown names fall back to the defaults."""
    theme = theme if theme in THEMES else DEFAULT_THEME
    tokens = dict(THEMES[theme])
    if theme == "high_contrast":
        accent_color = accent_hot = "#FFFF00"
    else:
        dark_shade, light_shade = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])
        accent_color = light_shade if theme == "light" else dark_shade
        accent_hot = mix(accent_color, "#FFFFFF" if theme == "dark" else "#000000", 0.82)
    tokens.update(
        accent=accent_color,
        accent_hot=accent_hot,
        border_hot=accent_color,
        selection=(
            accent_color if theme == "high_contrast"
            else mix(accent_color, tokens["panel"], 0.32 if theme == "dark" else 0.22)
        ),
    )
    for item in fields(Palette):
        setattr(PALETTE, item.name, tokens[item.name])


def font(size: str = "base", weight: str = "normal") -> tuple[str, int, str]:
    """Return a theme font tuple; ``size`` is small/base/medium/large/title/metric."""
    return (UI_FONT, _active_sizes[size], weight)


def text_options() -> dict[str, object]:
    """Options that theme a raw ``tk.Text`` or ``tk.Listbox`` like ttk inputs."""
    return {
        "background": PALETTE.field,
        "foreground": PALETTE.text,
        "insertbackground": PALETTE.text,
        "selectbackground": PALETTE.selection,
        "selectforeground": PALETTE.selection_text,
        "relief": tk.FLAT,
        "highlightthickness": 1,
        "highlightbackground": PALETTE.border,
        "highlightcolor": PALETTE.accent,
        "font": font(),
    }


def apply_theme(
    root: tk.Misc,
    *,
    theme: str = DEFAULT_THEME,
    accent: str = DEFAULT_ACCENT,
    high_contrast: bool = False,
    large_text: bool = False,
) -> ttk.Style:
    """Load the palette and configure every ttk style used by the application."""
    set_theme("high_contrast" if high_contrast else theme, accent)
    _active_sizes.clear()
    _active_sizes.update(_LARGE_TEXT_SIZES if large_text else _SIZES)
    p = PALETTE
    base = font()
    row_height = 34 if large_text else 28

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    root.configure(background=p.window)
    for pattern, value in (
        ("*TCombobox*Listbox.background", p.field),
        ("*TCombobox*Listbox.foreground", p.text),
        ("*TCombobox*Listbox.selectBackground", p.selection),
        ("*TCombobox*Listbox.selectForeground", p.selection_text),
        ("*Menu.background", p.panel_alt),
        ("*Menu.foreground", p.text),
        ("*Menu.activeBackground", p.selection),
        ("*Menu.activeForeground", p.selection_text),
    ):
        root.option_add(pattern, value)

    style.configure(
        ".",
        background=p.panel, foreground=p.text, fieldbackground=p.field,
        bordercolor=p.border, darkcolor=p.border, lightcolor=p.border,
        troughcolor=p.window, selectbackground=p.selection,
        selectforeground=p.selection_text, insertcolor=p.text, focuscolor=p.accent,
        font=base,
    )

    # Surfaces
    for name, background in (
        ("TFrame", p.panel), ("Content.TFrame", p.panel), ("Sidebar.TFrame", p.chrome),
        ("Toolbar.TFrame", p.chrome), ("Statusbar.TFrame", p.chrome),
        ("Card.TFrame", p.panel_alt), ("Header.TFrame", p.panel),
    ):
        style.configure(name, background=background)
    style.configure("Card.TFrame", bordercolor=p.border, relief="solid", borderwidth=1)
    style.configure("TSeparator", background=p.border)

    # Text
    labels = {
        "TLabel": (p.panel, p.text, base),
        "Muted.TLabel": (p.panel, p.muted, base),
        "Small.TLabel": (p.panel, p.muted, font("small")),
        "Toolbar.TLabel": (p.chrome, p.muted, base),
        "Statusbar.TLabel": (p.chrome, p.muted, font("small")),
        "Brand.TLabel": (p.chrome, p.text, font("large", "bold")),
        "AccentBrand.TLabel": (p.chrome, p.accent, font("small", "bold")),
        "NavSection.TLabel": (p.chrome, p.muted, font("small", "bold")),
        "Header.TLabel": (p.panel, p.text, font("title", "bold")),
        "Subheader.TLabel": (p.panel, p.muted, base),
        "Title.TLabel": (p.panel, p.text, font("large", "bold")),
        "Subtitle.TLabel": (p.panel, p.muted, base),
        "Section.TLabel": (p.panel, p.text, font("medium", "bold")),
        "CardTitle.TLabel": (p.panel, p.text, font("medium", "bold")),
        "Metric.TLabel": (p.panel_alt, p.text, font("metric", "bold")),
        "Card.TLabel": (p.panel_alt, p.text, base),
        "CardMuted.TLabel": (p.panel_alt, p.muted, font("small")),
        "CardHeading.TLabel": (p.panel_alt, p.text, font("medium", "bold")),
        "Badge.TLabel": (p.accent, p.on_accent, font("small", "bold")),
        "StatusDownloaded.TLabel": (p.panel, p.success, base),
        "StatusFailed.TLabel": (p.panel, p.danger, base),
        "StatusPending.TLabel": (p.panel, p.warning, base),
        "Success.TLabel": (p.panel, p.success, base),
        "Error.TLabel": (p.panel, p.danger, base),
    }
    for name, (background, foreground, typeface) in labels.items():
        style.configure(name, background=background, foreground=foreground, font=typeface)
    style.configure("Badge.TLabel", padding=(6, 1))

    # Buttons
    style.configure(
        "TButton", background=p.panel_alt, foreground=p.text, bordercolor=p.border,
        lightcolor=p.panel_alt, darkcolor=p.panel_alt, padding=(12, 6), relief="flat",
        focusthickness=1, focuscolor=p.accent,
    )
    style.map(
        "TButton",
        background=[("disabled", p.panel), ("pressed", p.selection), ("active", p.hover)],
        bordercolor=[("focus", p.accent), ("active", p.muted)],
        foreground=[("disabled", p.disabled)],
    )
    style.configure(
        "Accent.TButton", background=p.accent, foreground=p.on_accent, bordercolor=p.accent,
        lightcolor=p.accent, darkcolor=p.accent, font=font("base", "bold"),
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", p.panel_alt), ("pressed", p.accent), ("active", p.accent_hot)],
        foreground=[("disabled", p.disabled)],
    )
    style.configure(
        "Danger.TButton", background=p.panel_alt, foreground=p.danger, bordercolor=p.danger,
    )
    style.map("Danger.TButton", background=[("active", p.hover)])
    for name in ("Ghost.TButton", "Tool.TButton"):
        style.configure(
            name, background=p.panel, foreground=p.text, bordercolor=p.panel,
            lightcolor=p.panel, darkcolor=p.panel, padding=(8, 4),
        )
        style.map(
            name,
            background=[("pressed", p.selection), ("active", p.hover)],
            bordercolor=[("focus", p.accent)],
        )
    style.configure(
        "Chip.TButton", background=p.panel_alt, foreground=p.muted, bordercolor=p.border,
        padding=(10, 3), font=font("small"),
    )
    style.map("Chip.TButton", background=[("active", p.hover)], foreground=[("active", p.text)])
    style.configure(
        "ChipActive.TButton", background=p.selection, foreground=p.selection_text,
        bordercolor=p.accent, padding=(10, 3), font=font("small", "bold"),
    )
    style.map("ChipActive.TButton", background=[("active", p.selection)])
    for name, foreground in (("Nav.TButton", p.muted), ("NavActive.TButton", p.text)):
        background = p.hover if name == "NavActive.TButton" else p.chrome
        style.configure(
            name, anchor=tk.W, background=background, foreground=foreground,
            bordercolor=background, lightcolor=background, darkcolor=background,
            padding=(10, 7), relief="flat", font=base,
        )
        style.map(
            name,
            background=[("pressed", p.selection), ("active", p.hover)],
            foreground=[("active", p.text)],
            bordercolor=[("focus", p.accent)],
        )
    style.configure(
        "Header.TButton", background=p.panel, foreground=p.muted, bordercolor=p.border,
        padding=(10, 5),
    )
    style.map(
        "Header.TButton",
        background=[("active", p.hover)], foreground=[("active", p.text)],
        bordercolor=[("focus", p.accent)],
    )

    # Containers
    style.configure(
        "TLabelframe", background=p.panel, foreground=p.text, bordercolor=p.border,
        lightcolor=p.border, darkcolor=p.border, relief="solid", borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label", background=p.panel, foreground=p.muted,
        font=font("small", "bold"),
    )
    style.configure("TNotebook", background=p.panel, bordercolor=p.border, tabmargins=(0, 0, 0, 0))
    style.configure(
        "TNotebook.Tab", background=p.panel, foreground=p.muted, bordercolor=p.border,
        lightcolor=p.panel, padding=(14, 7),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", p.panel_alt), ("active", p.hover)],
        foreground=[("selected", p.text), ("active", p.text)],
        lightcolor=[("selected", p.accent)],
        bordercolor=[("selected", p.border)],
    )

    # Inputs
    for widget in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(
            widget, fieldbackground=p.field, foreground=p.text, bordercolor=p.border,
            lightcolor=p.field, darkcolor=p.field, arrowcolor=p.muted, padding=6,
            insertcolor=p.text,
        )
        style.map(
            widget,
            bordercolor=[("focus", p.accent)],
            lightcolor=[("focus", p.accent)],
            foreground=[("disabled", p.disabled)],
        )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", p.field)],
        foreground=[("readonly", p.text)],
        selectbackground=[("readonly", p.field)],
        selectforeground=[("readonly", p.text)],
        bordercolor=[("focus", p.accent)],
    )
    for widget in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            widget, background=p.panel, foreground=p.text, indicatorbackground=p.field,
            indicatorforeground=p.accent, upperbordercolor=p.border, lowerbordercolor=p.border,
        )
        style.map(
            widget,
            background=[("active", p.panel)],
            indicatorbackground=[("selected", p.accent), ("active", p.hover)],
            indicatorforeground=[("selected", p.on_accent)],
        )

    # Data views
    style.configure(
        "Treeview", background=p.field, fieldbackground=p.field, foreground=p.text,
        rowheight=row_height, bordercolor=p.border, lightcolor=p.field, darkcolor=p.field,
        relief="flat",
    )
    style.map(
        "Treeview",
        background=[("selected", p.selection)],
        foreground=[("selected", p.selection_text)],
    )
    style.configure(
        "Treeview.Heading", background=p.panel_alt, foreground=p.muted,
        bordercolor=p.border, lightcolor=p.panel_alt, darkcolor=p.panel_alt,
        relief="flat", padding=(8, 6), font=font("small", "bold"),
    )
    style.map("Treeview.Heading", background=[("active", p.hover)], foreground=[("active", p.text)])
    for orientation in ("Vertical", "Horizontal"):
        style.configure(
            f"{orientation}.TScrollbar", background=p.panel_alt, troughcolor=p.panel,
            bordercolor=p.panel, lightcolor=p.panel_alt, darkcolor=p.panel_alt,
            arrowcolor=p.muted, gripcount=0,
        )
        style.map(f"{orientation}.TScrollbar", background=[("active", p.hover)])
    style.configure(
        "Horizontal.TProgressbar", background=p.accent, troughcolor=p.field,
        bordercolor=p.border, lightcolor=p.accent, darkcolor=p.accent,
    )
    return style


set_theme()

"""Desktop shell widgets: navigation, status bar, toasts, notifications, shortcuts."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from datetime import datetime, timezone
from tkinter import ttk
from typing import Callable, Sequence

from ui_theme import PALETTE, font
from unityscraper.core.notifications import Notification, NotificationService

LEVEL_GLYPHS = {"info": "ℹ", "success": "✓", "warning": "!", "error": "✕"}


def level_color(level: str) -> str:
    return {
        "info": PALETTE.info,
        "success": PALETTE.success,
        "warning": PALETTE.warning,
        "error": PALETTE.danger,
    }.get(level, PALETTE.muted)


@dataclass(frozen=True)
class PageSpec:
    """One navigable page; ``show`` renders it into the content area."""

    key: str
    label: str
    group: str
    icon: str
    show: Callable[[], None]
    description: str = ""
    shortcut: str | None = None


class Sidebar(ttk.Frame):
    """Grouped navigation with an accent bar on the active page."""

    def __init__(
        self,
        parent: tk.Misc,
        pages: Sequence[PageSpec],
        *,
        brand_image: tk.PhotoImage | None,
        version: str,
        show_hints: bool,
    ) -> None:
        super().__init__(parent, style="Sidebar.TFrame", padding=(10, 14, 10, 10))
        self._rows: dict[str, tuple[tk.Frame, ttk.Button, tk.Label | None]] = {}

        brand = ttk.Frame(self, style="Sidebar.TFrame")
        brand.pack(fill=tk.X, padx=4, pady=(0, 10))
        if brand_image is not None:
            ttk.Label(brand, image=brand_image, style="Brand.TLabel").pack(side=tk.LEFT, padx=(0, 9))
        text = ttk.Frame(brand, style="Sidebar.TFrame")
        text.pack(side=tk.LEFT, fill=tk.X)
        ttk.Label(text, text="UnityScraper", style="Brand.TLabel").pack(anchor=tk.W)
        ttk.Label(text, text=version, style="AccentBrand.TLabel").pack(anchor=tk.W)

        # The nav list scrolls with the wheel when the window is too short to show it all.
        self._canvas = tk.Canvas(self, background=PALETTE.chrome, highlightthickness=0, borderwidth=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        nav = ttk.Frame(self._canvas, style="Sidebar.TFrame")
        window = self._canvas.create_window(0, 0, window=nav, anchor=tk.NW)
        nav.bind("<Configure>", lambda _event: self._canvas.configure(
            scrollregion=self._canvas.bbox("all"), width=nav.winfo_reqwidth()
        ))
        self._canvas.bind(
            "<Configure>", lambda event: self._canvas.itemconfigure(window, width=event.width)
        )
        self.bind("<Enter>", lambda _event: self._bind_wheel(True))
        self.bind("<Leave>", self._leave)

        group = None
        for page in pages:
            if page.group != group:
                group = page.group
                ttk.Label(nav, text=group.upper(), style="NavSection.TLabel").pack(
                    anchor=tk.W, padx=8, pady=(10, 2)
                )
            row = tk.Frame(nav, background=PALETTE.chrome)
            row.pack(fill=tk.X)
            indicator = tk.Frame(row, width=3, background=PALETTE.chrome)
            indicator.pack(side=tk.LEFT, fill=tk.Y)
            hint = None
            if show_hints and page.shortcut:
                hint = tk.Label(
                    row, text=page.shortcut, background=PALETTE.chrome,
                    foreground=PALETTE.disabled, font=font("small"), padx=6,
                )
                hint.pack(side=tk.RIGHT)
                hint.bind("<Button-1>", lambda _event, action=page.show: action())
            button = ttk.Button(
                row, text=f"{page.icon}   {page.label}", style="Nav.TButton", command=page.show
            )
            button.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self._rows[page.key] = (indicator, button, hint)

    def _leave(self, event: tk.Event) -> None:
        # Moving onto a child button also fires <Leave>; keep the wheel bound until truly outside.
        under = self.winfo_containing(event.x_root, event.y_root)
        if under is None or not str(under).startswith(str(self)):
            self._bind_wheel(False)

    def _bind_wheel(self, active: bool) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            if active:
                self.bind_all(sequence, self._scroll)
            else:
                self.unbind_all(sequence)

    def _scroll(self, event: tk.Event) -> None:
        if self._canvas.winfo_height() >= self._canvas.bbox("all")[3]:
            return
        step = -1 if event.num == 4 or event.delta > 0 else 1
        self._canvas.yview_scroll(step * 2, "units")

    def set_active(self, key: str) -> None:
        for page_key, (indicator, button, hint) in self._rows.items():
            active = page_key == key
            indicator.configure(background=PALETTE.accent if active else PALETTE.chrome)
            button.configure(style="NavActive.TButton" if active else "Nav.TButton")
            if hint is not None:
                hint.configure(background=PALETTE.hover if active else PALETTE.chrome)


class StatusBar(ttk.Frame):
    """Window-wide status line with a background-job counter."""

    def __init__(self, parent: tk.Misc, right_text: str) -> None:
        super().__init__(parent, style="Statusbar.TFrame", padding=(12, 4))
        self._text = tk.StringVar(value="Ready")
        self._jobs = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._text, style="Statusbar.TLabel").pack(side=tk.LEFT)
        ttk.Label(self, text=right_text, style="Statusbar.TLabel").pack(side=tk.RIGHT)
        ttk.Label(self, textvariable=self._jobs, style="Statusbar.TLabel").pack(
            side=tk.RIGHT, padx=(0, 18)
        )

    def set_text(self, text: str) -> None:
        self._text.set(text)

    def set_jobs(self, count: int) -> None:
        self._jobs.set("" if count <= 0 else f"⟳ {count} background task{'s' * (count != 1)}")


class ToastManager:
    """Short-lived notices stacked in the window's bottom-right corner."""

    MAX_VISIBLE = 4

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._toasts: list[tk.Toplevel] = []

    def show(self, level: str, title: str, message: str = "") -> None:
        while len(self._toasts) >= self.MAX_VISIBLE:
            self._dismiss(self._toasts[0])
        toast = tk.Toplevel(self.root)
        toast.withdraw()
        toast.overrideredirect(True)
        toast.configure(background=PALETTE.border)
        try:
            toast.attributes("-topmost", True)
        except tk.TclError:
            pass
        body = tk.Frame(toast, background=PALETTE.panel_alt, padx=12, pady=10)
        body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Frame(body, width=3, background=level_color(level)).pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        text = tk.Frame(body, background=PALETTE.panel_alt)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        widgets = [toast, body, text]
        widgets.append(tk.Label(
            text, text=f"{LEVEL_GLYPHS.get(level, '')}  {title}", anchor=tk.W, justify=tk.LEFT,
            background=PALETTE.panel_alt, foreground=PALETTE.text, font=font("base", "bold"),
            wraplength=300,
        ))
        widgets[-1].pack(fill=tk.X)
        if message:
            widgets.append(tk.Label(
                text, text=message, anchor=tk.W, justify=tk.LEFT, wraplength=300,
                background=PALETTE.panel_alt, foreground=PALETTE.muted, font=font("small"),
            ))
            widgets[-1].pack(fill=tk.X, pady=(3, 0))
        for widget in widgets:
            widget.bind("<Button-1>", lambda _event, item=toast: self._dismiss(item))
        self._toasts.append(toast)
        self._layout()
        toast.deiconify()
        toast.after(8000 if level == "error" else 5000, lambda: self._dismiss(toast))

    def _dismiss(self, toast: tk.Toplevel) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            toast.destroy()
            self._layout()

    def _layout(self) -> None:
        if not self.root.winfo_exists():
            return
        right = self.root.winfo_rootx() + self.root.winfo_width() - 16
        bottom = self.root.winfo_rooty() + self.root.winfo_height() - 40
        for toast in reversed(self._toasts):
            toast.update_idletasks()
            width, height = max(toast.winfo_reqwidth(), 300), toast.winfo_reqheight()
            bottom -= height
            toast.geometry(f"{width}x{height}+{right - width}+{bottom}")
            bottom -= 8


def relative_time(timestamp: str, now: datetime | None = None) -> str:
    """Format an ISO or SQLite timestamp as '5m ago'; naive values are treated as UTC."""
    try:
        moment = datetime.fromisoformat(str(timestamp).strip())
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    seconds = int(((now or datetime.now(timezone.utc)) - moment).total_seconds())
    if seconds < 0:
        return "just now"
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit} ago"
    return "just now"


def format_size(size: object) -> str:
    """Format a byte count as '1.5 MB'; empty or zero shows an em dash."""
    if not size:
        return "—"
    value = float(size)  # type: ignore[arg-type]
    for suffix in ("B", "KB", "MB", "GB"):
        if value < 1024 or suffix == "GB":
            return f"{value:.1f} {suffix}"
        value /= 1024
    return "—"


class NotificationPanel(tk.Toplevel):
    """Drop-down notification history anchored under a header button."""

    def __init__(
        self,
        root: tk.Tk,
        anchor: tk.Widget,
        service: NotificationService,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(root)
        self.service = service
        self.on_change = on_change
        self.overrideredirect(True)
        self.configure(background=PALETTE.border)
        frame = ttk.Frame(self, padding=12, style="Card.TFrame")
        frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        header = ttk.Frame(frame, style="Card.TFrame")
        header.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(header, text="Notifications", style="CardHeading.TLabel").pack(side=tk.LEFT)
        ttk.Button(header, text="Clear", style="Ghost.TButton", command=self._clear).pack(side=tk.RIGHT)
        ttk.Button(
            header, text="Mark all read", style="Ghost.TButton", command=self._mark_read
        ).pack(side=tk.RIGHT, padx=(0, 4))

        self.listing = tk.Frame(frame, background=PALETTE.panel_alt)
        self.listing.pack(fill=tk.BOTH, expand=True)
        self._render()

        width, height = 380, 440
        x = anchor.winfo_rootx() + anchor.winfo_width() - width
        y = anchor.winfo_rooty() + anchor.winfo_height() + 6
        self.geometry(f"{width}x{height}+{max(x, 0)}+{y}")
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<FocusOut>", self._focus_out)
        self.after(10, self.focus_force)

    def _render(self) -> None:
        for child in self.listing.winfo_children():
            child.destroy()
        items: list[Notification] = self.service.recent(30)
        if not items:
            tk.Label(
                self.listing, text="You're all caught up.", background=PALETTE.panel_alt,
                foreground=PALETTE.muted, font=font(), pady=24,
            ).pack(fill=tk.X)
            return
        for item in items:
            row = tk.Frame(self.listing, background=PALETTE.panel_alt, pady=6)
            row.pack(fill=tk.X)
            tk.Label(
                row, text=LEVEL_GLYPHS.get(item.level, "•"), width=2,
                background=PALETTE.panel_alt, foreground=level_color(item.level),
                font=font("base", "bold"),
            ).pack(side=tk.LEFT, anchor=tk.N)
            text = tk.Frame(row, background=PALETTE.panel_alt)
            text.pack(side=tk.LEFT, fill=tk.X, expand=True)
            title_row = tk.Frame(text, background=PALETTE.panel_alt)
            title_row.pack(fill=tk.X)
            tk.Label(
                title_row, text=item.title, anchor=tk.W, background=PALETTE.panel_alt,
                foreground=PALETTE.text if not item.read else PALETTE.muted,
                font=font("base", "normal" if item.read else "bold"),
            ).pack(side=tk.LEFT)
            tk.Label(
                title_row, text=relative_time(item.created_at), background=PALETTE.panel_alt,
                foreground=PALETTE.muted, font=font("small"),
            ).pack(side=tk.RIGHT)
            if item.message:
                tk.Label(
                    text, text=item.message, anchor=tk.W, justify=tk.LEFT, wraplength=310,
                    background=PALETTE.panel_alt, foreground=PALETTE.muted, font=font("small"),
                ).pack(fill=tk.X)

    def _mark_read(self) -> None:
        self.service.mark_all_read()
        self._render()
        self.on_change()

    def _clear(self) -> None:
        self.service.clear()
        self._render()
        self.on_change()

    def _focus_out(self, _event: tk.Event) -> None:
        self.after(100, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        if not self.winfo_exists():
            return
        focused = self.focus_get()
        if focused is None or not str(focused).startswith(str(self)):
            self.destroy()


class ShortcutSheet(tk.Toplevel):
    """Modal list of keyboard shortcuts (F1)."""

    def __init__(self, root: tk.Tk, shortcuts: Sequence[tuple[str, str]]) -> None:
        super().__init__(root)
        self.title("Keyboard shortcuts")
        self.configure(background=PALETTE.panel)
        self.transient(root)
        self.resizable(False, False)
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="Keyboard shortcuts", style="Title.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 12)
        )
        for row, (keys, action) in enumerate(shortcuts, start=1):
            ttk.Label(frame, text=keys, style="Badge.TLabel").grid(
                row=row, column=0, sticky=tk.W, pady=3, padx=(0, 16)
            )
            ttk.Label(frame, text=action).grid(row=row, column=1, sticky=tk.W, pady=3)
        ttk.Button(frame, text="Close", command=self.destroy).grid(
            row=len(shortcuts) + 1, column=1, sticky=tk.E, pady=(16, 0)
        )
        self.bind("<Escape>", lambda _event: self.destroy())
        self.after(10, self.focus_force)

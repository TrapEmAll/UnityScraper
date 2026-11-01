"""Home page: library metrics, items needing attention, recent activity and shortcuts."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Sequence

from ui_theme import PALETTE, font
from unityscraper.app.desktop.shell import relative_time
from unityscraper.domains.library.activity import ATTENTION_DAYS, ActivityFeed, ActivityItem

FEED_LIMIT = 25
ATTENTION_SHOWN = 8
WRAP = 380
# Attention item kind -> (page key, page label) for its "Go to" button.
ATTENTION_TARGETS = {
    "backup": ("backups", "Backups"),
    "backup_scan": ("backups", "Backups"),
    "catalog_sync": ("add_games", "Add Games"),
    "title_updates": ("downloads", "Downloads"),
    "watch_folder": ("backups", "Backups"),
    "watchlist": ("downloads", "Downloads"),
}
QUICK_ACTIONS = (
    ("Add games", "add_games"),
    ("Scan a backup folder", "backups"),
    ("Check watched title updates", "downloads"),
    ("Archive health", "health"),
    ("Settings", "settings"),
)
METRICS = (
    ("games", "Games"),
    ("covers", "Covers downloaded"),
    ("updates", "Title updates downloaded / known"),
    ("failed", "Failed items"),
)


def status_color(status: str) -> str:
    """Dot color for an activity status."""
    status = status.lower()
    if status in ("failed", "error"):
        return PALETTE.danger
    if status in ("running", "interrupted", "partial", "skipped", "warning", "new"):
        return PALETTE.warning
    return PALETTE.success if status else PALETTE.muted


class _ScrollArea:
    """Vertical Canvas+Frame scroller; the wheel is bound only while the pointer is over it."""

    def __init__(self, parent: tk.Misc) -> None:
        self.canvas = tk.Canvas(
            parent, background=PALETTE.panel, highlightthickness=0, borderwidth=0,
            yscrollincrement=24,
        )
        self.scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self._set_scrollbar)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.frame = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, window=self.frame, anchor="nw")
        self.frame.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>", lambda event: self.canvas.itemconfigure(self._window, width=event.width)
        )
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._leave)
        self.canvas.bind("<Destroy>", self._unbind_wheel)

    def _set_scrollbar(self, first: str, last: str) -> None:
        self.scrollbar.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.grid_remove()
        else:
            self.scrollbar.grid()

    def _hovered(self, x_root: int, y_root: int) -> bool:
        path = str(self.canvas.tk.call("winfo", "containing", x_root, y_root))
        canvas = str(self.canvas)
        return path == canvas or path.startswith(canvas + ".")

    def _bind_wheel(self, _event: tk.Event | None = None) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind_all(sequence, self._on_wheel)

    def _unbind_wheel(self, _event: tk.Event | None = None) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(sequence)

    def _leave(self, event: tk.Event) -> None:
        # Crossing into a child widget also fires <Leave>; keep the wheel while still inside.
        if not self._hovered(event.x_root, event.y_root):
            self._unbind_wheel()

    def _on_wheel(self, event: tk.Event) -> None:
        if not self._hovered(event.x_root, event.y_root):
            self._unbind_wheel()
            return
        if self.canvas.yview() == (0.0, 1.0):
            return
        up = event.num == 4 or getattr(event, "delta", 0) > 0
        self.canvas.yview_scroll(-3 if up else 3, "units")


class HomePage:
    """Landing page: metrics, attention list, activity feed and quick actions."""

    def __init__(self, app: Any) -> None:
        self.app = app
        app._page_header(
            "Home",
            "Your library at a glance: what changed recently and what needs a look.",
        )
        body = ttk.Frame(app.content)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.scroll = _ScrollArea(body)
        page = self.scroll.frame
        page.columnconfigure(0, weight=1)

        self.metric_vars = self._build_metrics(page)
        columns = ttk.Frame(page)
        columns.grid(row=1, column=0, sticky="nsew", pady=(24, 0))
        columns.columnconfigure((0, 1), weight=1, uniform="home")
        self.attention_list = self._build_card(
            columns, 0, "Needs attention",
            f"Failures from the last {ATTENTION_DAYS} days and new items to review.",
        )
        self.activity_list = self._build_card(
            columns, 1, "Recent activity", "Latest scans, backups, syncs, scrapes and checks."
        )
        self._build_quick_actions(page)
        self.refresh()

    # ------------------------------------------------------------ layout

    def _build_metrics(self, page: ttk.Frame) -> dict[str, tk.StringVar]:
        metrics = ttk.Frame(page)
        metrics.grid(row=0, column=0, sticky="ew")
        variables: dict[str, tk.StringVar] = {}
        for index, (key, caption) in enumerate(METRICS):
            metrics.columnconfigure(index, weight=1, uniform="metric")
            card = ttk.Frame(metrics, style="Card.TFrame", padding=(16, 12))
            card.grid(row=0, column=index, sticky="nsew", padx=(12 if index else 0, 0))
            variables[key] = tk.StringVar(value="–")
            ttk.Label(card, textvariable=variables[key], style="Metric.TLabel").pack(anchor=tk.W)
            ttk.Label(card, text=caption, style="CardMuted.TLabel").pack(anchor=tk.W, pady=(2, 0))
        return variables

    def _build_card(self, parent: ttk.Frame, column: int, title: str, caption: str) -> tk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.grid(row=0, column=column, sticky="nsew", padx=(12, 0) if column else (0, 12))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=title, style="CardHeading.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(card, text=caption, style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(2, 12)
        )
        listing = tk.Frame(card, background=PALETTE.panel_alt)
        listing.grid(row=2, column=0, sticky="nsew")
        self._message(listing, "Loading…")
        return listing

    def _build_quick_actions(self, page: ttk.Frame) -> None:
        ttk.Label(page, text="Quick actions", style="Section.TLabel").grid(
            row=2, column=0, sticky="w", pady=(24, 8)
        )
        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, sticky="w", pady=(0, 8))
        for index, (text, key) in enumerate(QUICK_ACTIONS):
            ttk.Button(
                actions,
                text=text,
                style="TButton" if index else "Accent.TButton",
                command=lambda key=key: self.app.navigate(key),
            ).pack(side=tk.LEFT, padx=(0, 8))

    # ------------------------------------------------------------ data

    def refresh(self) -> None:
        """Reload metrics, attention items and the activity feed in the background."""
        database_path = self.app.database.db_path

        def work() -> tuple[dict[str, int], list[ActivityItem], list[ActivityItem]]:
            feed = ActivityFeed(database_path)
            counts = self.app.library.get_dashboard_counts()
            return counts, feed.attention(), feed.recent(FEED_LIMIT)

        self.app.run_background("Loading home", work, self._render, self._render_error)

    def _render(
        self, result: tuple[dict[str, int], list[ActivityItem], list[ActivityItem]]
    ) -> None:
        if not self.scroll.canvas.winfo_exists():
            return  # The user left the page before loading finished.
        counts, attention, recent = result
        self.metric_vars["games"].set(f"{counts['games']:,}")
        self.metric_vars["covers"].set(f"{counts['covers_downloaded']:,}")
        self.metric_vars["updates"].set(
            f"{counts['updates_downloaded']:,} / {counts['updates_available']:,}"
        )
        self.metric_vars["failed"].set(f"{counts['failed']:,}")
        self._render_attention(attention)
        self._render_activity(recent)

    def _render_error(self, error: Exception) -> None:
        if not self.scroll.canvas.winfo_exists():
            return
        for listing in (self.attention_list, self.activity_list):
            self._message(listing, f"Couldn't load this section: {error}")

    def _render_attention(self, items: Sequence[ActivityItem]) -> None:
        self._clear(self.attention_list)
        if not items:
            row = self._row(self.attention_list, "completed", "All clear")
            self._detail(row, "No recent failures and nothing new to review.")
            return
        for item in items[:ATTENTION_SHOWN]:
            row = self._row(self.attention_list, item.status, item.title)
            self._detail(row, item.detail)
            key, label = ATTENTION_TARGETS.get(item.kind, ("library", "Library"))
            ttk.Button(
                row, text=f"Go to {label}", command=lambda key=key: self.app.navigate(key)
            ).grid(row=0, column=2, rowspan=2, sticky="e", padx=(12, 0))
        hidden = len(items) - ATTENTION_SHOWN
        if hidden > 0:
            ttk.Label(
                self.attention_list, text=f"+ {hidden} more", style="CardMuted.TLabel"
            ).pack(anchor=tk.W, pady=(4, 0))

    def _render_activity(self, items: Sequence[ActivityItem]) -> None:
        self._clear(self.activity_list)
        if not items:
            row = self._row(self.activity_list, "", "No activity yet")
            self._detail(
                row, "Scrapes, backup scans, catalog syncs and update checks will appear here."
            )
            return
        for item in items:
            row = self._row(self.activity_list, item.status, item.title)
            self._detail(row, item.detail)
            ttk.Label(row, text=relative_time(item.timestamp), style="CardMuted.TLabel").grid(
                row=0, column=2, sticky="ne", padx=(12, 0)
            )

    # ------------------------------------------------------------ widgets

    @staticmethod
    def _clear(listing: tk.Frame) -> None:
        for child in listing.winfo_children():
            child.destroy()

    def _message(self, listing: tk.Frame, text: str) -> None:
        self._clear(listing)
        ttk.Label(listing, text=text, style="CardMuted.TLabel", wraplength=WRAP).pack(anchor=tk.W)

    @staticmethod
    def _row(listing: tk.Frame, status: str, title: str) -> tk.Frame:
        row = tk.Frame(listing, background=PALETTE.panel_alt)
        row.pack(fill=tk.X, pady=(0, 10))
        row.columnconfigure(1, weight=1)
        tk.Label(
            row, text="●", background=PALETTE.panel_alt, foreground=status_color(status),
            font=font("small"),
        ).grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=(2, 0))
        ttk.Label(row, text=title, style="Card.TLabel", wraplength=WRAP).grid(
            row=0, column=1, sticky="w"
        )
        return row

    @staticmethod
    def _detail(row: tk.Frame, text: str) -> None:
        if text:
            ttk.Label(row, text=text, style="CardMuted.TLabel", wraplength=WRAP).grid(
                row=1, column=1, sticky="w", pady=(2, 0)
            )


__all__ = ["HomePage", "status_color"]

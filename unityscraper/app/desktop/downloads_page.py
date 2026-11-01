"""Downloads page: title update watchlist plus the legacy download tools."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Sequence

from platform_support import open_path
from ui_theme import PALETTE
from unityscraper.app.desktop.shell import relative_time
from unityscraper.core.paths import DOWNLOADS_DIR
from unityscraper.domains.library.update_watch import (
    UpdateCheckResult,
    UpdateWatchService,
    make_xboxunity_collector,
)

INTERVAL_CHOICES = ("6", "12", "24", "48", "168")
COLUMNS = (
    ("name", "Game", 260),
    ("titleid", "TitleID", 100),
    ("known", "Known updates", 110),
    ("new", "New", 60),
    ("checked", "Last checked", 120),
    ("status", "Status", 220),
)


def notify_check_results(app: Any, results: Sequence[UpdateCheckResult]) -> None:
    """Summarize a watchlist check as app notifications (also used by the startup check)."""
    failed = [result for result in results if result.error]
    found = [result for result in results if not result.error and result.new_updates]
    if found:
        total = sum(result.new_updates for result in found)
        app.notify(
            "success",
            "Title updates found",
            f"{total} new update(s) for {len(found)} game(s)",
            source="Title update watch",
        )
    elif len(failed) < len(results) or not results:
        app.notify(
            "info",
            "No new title updates",
            f"Checked {len(results) - len(failed)} game(s); no new updates were published.",
            source="Title update watch",
        )
    if failed:
        details = "; ".join(f"{result.name}: {result.error}" for result in failed[:3])
        more = f" (+{len(failed) - 3} more)" if len(failed) > 3 else ""
        app.notify(
            "warning",
            "Some title update checks failed",
            f"{len(failed)} of {len(results)} failed. {details}{more}",
            source="Title update watch",
        )


class DownloadsPage:
    """Title update watchlist with scheduled checks, plus the legacy download tools."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.service = UpdateWatchService(app.database.db_path)
        self.schedule = self.service.schedule()
        self._checking = False

        app._page_header(
            "Downloads",
            "Watch games for new XboxUnity title updates and open the download tools.",
        )
        self.body = ttk.Frame(app.content)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(0, weight=1)

        self._build_watchlist_card()
        self._build_tools_card()
        self.refresh()

    # ------------------------------------------------------------ layout

    def _build_watchlist_card(self) -> None:
        card = ttk.Frame(self.body, style="Card.TFrame", padding=16)
        card.grid(row=0, column=0, sticky="nsew")
        card.columnconfigure(0, weight=1)
        card.rowconfigure(2, weight=1)

        ttk.Label(card, text="Title update watchlist", style="CardHeading.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card,
            text=(
                "Watched games are re-checked on XboxUnity. Updates published since the "
                "last check are counted as new until you acknowledge them."
            ),
            style="CardMuted.TLabel",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        self.list_frame = ttk.Frame(card, style="Card.TFrame")
        self.list_frame.grid(row=2, column=0, sticky="nsew")
        self.list_frame.columnconfigure(0, weight=1)
        self.list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            self.list_frame,
            columns=[key for key, _, _ in COLUMNS],
            show="headings",
            selectmode="extended",
            height=10,
        )
        for key, heading, width in COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, anchor="w", stretch=key in ("name", "status"))
        self.tree.tag_configure("new", foreground=PALETTE.success)
        scrollbar = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.empty_frame = ttk.Frame(card, style="Card.TFrame", padding=(0, 24))
        ttk.Label(
            self.empty_frame, text="No games on your watchlist yet", style="Card.TLabel"
        ).pack(anchor=tk.W)
        ttk.Label(
            self.empty_frame,
            text="Open a game in the library and turn on the watch toggle in its details.",
            style="CardMuted.TLabel",
        ).pack(anchor=tk.W, pady=(4, 12))
        ttk.Button(
            self.empty_frame,
            text="Open Library",
            style="Accent.TButton",
            command=lambda: self.app.navigate("library"),
        ).pack(anchor=tk.W)

        actions = ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.check_all_button = ttk.Button(
            actions, text="Check All", style="Accent.TButton", command=lambda: self._check(None)
        )
        self.check_all_button.pack(side=tk.LEFT)
        self.check_selected_button = ttk.Button(
            actions, text="Check Selected", command=self._check_selected
        )
        self.check_selected_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Acknowledge New", command=self._acknowledge).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(actions, text="Remove From Watchlist", command=self._remove).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(
            actions, text="Add From Library", command=lambda: self.app.navigate("library")
        ).pack(side=tk.LEFT, padx=(8, 0))

        state = self.schedule.status()
        self.auto_var = tk.BooleanVar(value=bool(state.get("enabled")))
        self.interval_var = tk.StringVar(value=str(state.get("interval_hours", 24)))
        schedule_row = ttk.Frame(card, style="Card.TFrame")
        schedule_row.grid(row=4, column=0, sticky="w", pady=(12, 0))
        ttk.Checkbutton(
            schedule_row,
            text="Automatic check every",
            variable=self.auto_var,
            command=self._save_schedule,
        ).pack(side=tk.LEFT)
        interval = ttk.Combobox(
            schedule_row,
            textvariable=self.interval_var,
            values=INTERVAL_CHOICES,
            state="readonly",
            width=5,
        )
        interval.pack(side=tk.LEFT, padx=(6, 6))
        interval.bind("<<ComboboxSelected>>", lambda _event: self._save_schedule())
        ttk.Label(
            schedule_row, text="hours (runs when the app starts)", style="CardMuted.TLabel"
        ).pack(side=tk.LEFT)

    def _build_tools_card(self) -> None:
        card = ttk.Frame(self.body, style="Card.TFrame", padding=16)
        card.grid(row=1, column=0, sticky="ew", pady=(16, 0))
        ttk.Label(card, text="Download tools", style="CardHeading.TLabel").pack(anchor=tk.W)
        ttk.Label(
            card,
            text=(
                "The scraper engine, retry controls, queue, rate limiting and download logs "
                "remain available in Advanced Tools."
            ),
            style="CardMuted.TLabel",
            wraplength=760,
        ).pack(anchor=tk.W, pady=(4, 12))
        row = ttk.Frame(card, style="Card.TFrame")
        row.pack(anchor=tk.W)
        ttk.Button(
            row, text="Open Advanced Download Tools", command=self.app._open_legacy_gui
        ).pack(side=tk.LEFT)
        ttk.Button(row, text="Open Download Folder", command=self._open_downloads).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(row, text="Open GUI Log", command=self.app._open_log).pack(
            side=tk.LEFT, padx=(8, 0)
        )

    # ------------------------------------------------------------ data

    def refresh(self) -> None:
        """Reload the watchlist rows from the database."""
        if not self.tree.winfo_exists():
            return
        titles = self.service.watched()
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for title in titles:
            if title.last_status == "failed":
                status = f"Failed: {title.last_error or 'unknown error'}"
            elif title.last_status == "ok":
                status = "Up to date" if not title.new_update_count else "New updates"
            else:
                status = "Not checked yet"
            self.tree.insert(
                "",
                tk.END,
                iid=title.titleid,
                values=(
                    title.name,
                    title.titleid,
                    title.known_update_count,
                    title.new_update_count or "",
                    relative_time(title.last_checked_at) if title.last_checked_at else "Never",
                    status,
                ),
                tags=("new",) if title.new_update_count else (),
            )
        self.tree.selection_set([iid for iid in selected if self.tree.exists(iid)])
        if titles:
            self.empty_frame.grid_remove()
            self.list_frame.grid()
        else:
            self.list_frame.grid_remove()
            self.empty_frame.grid(row=2, column=0, sticky="nsew")
        enabled = "!disabled" if titles and not self._checking else "disabled"
        self.check_all_button.state([enabled])
        self.check_selected_button.state([enabled])

    def _selected(self) -> list[str]:
        selected = list(self.tree.selection())
        if not selected:
            self.app.set_status("Select one or more games in the watchlist first")
        return selected

    # ------------------------------------------------------------ actions

    def _check_selected(self) -> None:
        titleids = self._selected()
        if titleids:
            self._check(titleids)

    def _check(self, titleids: list[str] | None) -> None:
        if self._checking:
            return
        self._checking = True
        self.refresh()
        service = self.service
        collect = make_xboxunity_collector()

        def progress(index: int, total: int, name: str) -> None:
            self.app.set_status(f"Checking title updates {index}/{total}: {name}")

        def work() -> list[UpdateCheckResult]:
            if titleids is None:
                return service.check_all(collect, progress)
            results = []
            for index, titleid in enumerate(titleids, start=1):
                progress(index, len(titleids), titleid)
                results.append(service.check(titleid, collect))
            return results

        def done(results: list[UpdateCheckResult]) -> None:
            self._checking = False
            notify_check_results(self.app, results)
            self.refresh()

        def failed(error: Exception) -> None:
            self._checking = False
            self.app.notify("error", "Title update check failed", str(error))
            self.refresh()

        self.app.run_background("Checking title updates", work, done, failed)

    def _acknowledge(self) -> None:
        selected = list(self.tree.selection())
        if selected:
            for titleid in selected:
                self.service.acknowledge(titleid)
        else:
            self.service.acknowledge_all()
        self.refresh()

    def _remove(self) -> None:
        for titleid in self._selected():
            self.service.set_watched(titleid, False)
        self.refresh()

    def _save_schedule(self) -> None:
        self.schedule.configure(self.auto_var.get(), int(self.interval_var.get()))
        state = self.schedule.status()
        self.interval_var.set(str(state.get("interval_hours", self.interval_var.get())))
        self.app.set_status(
            f"Automatic title update check every {state.get('interval_hours')} h"
            if self.auto_var.get()
            else "Automatic title update check turned off"
        )

    def _open_downloads(self) -> None:
        try:
            open_path(DOWNLOADS_DIR)
        except (OSError, RuntimeError) as exc:
            self.app.notify("error", "Unable to open", str(exc))

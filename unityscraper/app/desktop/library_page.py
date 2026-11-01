"""Game Library page: list and grid views, filters, personal game data and bulk actions."""

from __future__ import annotations

import csv
import queue
import sqlite3
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Iterable, Mapping

from platform_support import open_path
from ui_theme import PALETTE, font, text_options
from unityscraper.core.config import read_config, update_config
from unityscraper.core.paths import DOWNLOADS_DIR, EXPORTS_DIR
from unityscraper.app.desktop.shell import format_size
from unityscraper.core.thumbnails import ThumbnailCache
from unityscraper.domains.library import GameSummary
from unityscraper.domains.library.update_watch import UpdateWatchService
from unityscraper.domains.library.user_data import (
    PLAY_STATUSES,
    GameUserData,
    GameUserDataService,
)

CHIPS = ("All", "Favorites", "Needs updates", "Complete", "Needs attention", "Watched")
SORT_KEYS = ("Name", "TitleID", "Publisher", "Updates", "Last scraped")
ANY_STATUS = "Any status"
NO_STATUS = "No status"
ANY_TAG = "Any tag"
GRID_ART = (150, 210)
DETAIL_ART = (80, 112)
CARD_PAD = 10
CARD_GAP = 12
CARD_W = GRID_ART[0] + 2 * CARD_PAD
CARD_H = GRID_ART[1] + 64

# (column, heading, width, anchor, stretch, sort key)
TREE_COLUMNS = (
    ("fav", "★", 32, tk.CENTER, False, "Favorite"),
    ("name", "Game", 170, tk.W, True, "Name"),
    ("titleid", "TitleID", 90, tk.CENTER, False, "TitleID"),
    ("publisher", "Publisher", 150, tk.W, False, "Publisher"),
    ("updates", "Updates", 80, tk.CENTER, False, "Updates"),
    ("status", "Status", 120, tk.CENTER, False, "Status"),
    ("play", "Play status", 100, tk.CENTER, False, "Play status"),
)


def summary_status(game: GameSummary) -> str:
    """One-word health of a game's title updates."""
    if game.updates_failed:
        return "Needs attention"
    if game.updates_total and game.updates_downloaded == game.updates_total:
        return "Complete"
    if game.updates_total:
        return "Updates available"
    return "Metadata only"


def _play_rank(status: str) -> int:
    return PLAY_STATUSES.index(status) if status in PLAY_STATUSES else 0


_SORT_FIELDS: dict[str, Callable[[GameSummary, GameUserData], Any]] = {
    "Name": lambda game, _data: game.name.casefold(),
    "TitleID": lambda game, _data: game.titleid.upper(),
    "Publisher": lambda game, _data: game.publisher.casefold(),
    "Updates": lambda game, _data: (game.updates_total, game.updates_downloaded),
    "Last scraped": lambda game, _data: game.last_scraped or "",
    "Favorite": lambda _game, data: data.favorite,
    "Status": lambda game, _data: summary_status(game),
    "Play status": lambda _game, data: _play_rank(data.play_status),
}


def _matches_chip(chip: str, game: GameSummary, data: GameUserData, watched: set[str]) -> bool:
    if chip == "Favorites":
        return data.favorite
    if chip == "Needs updates":
        return game.updates_downloaded < game.updates_total
    if chip == "Complete":
        return summary_status(game) == "Complete"
    if chip == "Needs attention":
        return game.updates_failed > 0
    if chip == "Watched":
        return game.titleid.upper() in watched
    return True


def filter_and_sort(
    games: Iterable[GameSummary],
    user_data: Mapping[str, GameUserData],
    watched: Iterable[str],
    *,
    chip: str = "All",
    play_status: str | None = None,
    tag: str | None = None,
    sort_key: str = "Name",
    descending: bool = False,
) -> list[GameSummary]:
    """Apply the library chip, play-status (None = any, "" = none) and tag filters, then sort.

    ``user_data`` is keyed by upper-case TitleID; missing games use defaults. Ties are
    always broken by name, then TitleID, ascending.
    """
    if chip not in CHIPS:
        raise ValueError(f"Unknown filter: {chip}")
    field = _SORT_FIELDS.get(sort_key)
    if field is None:
        raise ValueError(f"Unknown sort key: {sort_key}")
    watched_ids = {titleid.upper() for titleid in watched}
    wanted_tag = tag.casefold() if tag else None
    rows: list[tuple[GameSummary, GameUserData]] = []
    for game in games:
        key = game.titleid.upper()
        data = user_data.get(key) or GameUserData(key)
        if not _matches_chip(chip, game, data, watched_ids):
            continue
        if play_status is not None and data.play_status != play_status:
            continue
        if wanted_tag and wanted_tag not in {value.casefold() for value in data.tags}:
            continue
        rows.append((game, data))
    rows.sort(key=lambda row: (row[0].name.casefold(), row[0].titleid))
    rows.sort(key=lambda row: field(*row), reverse=descending)  # stable: ties keep name order
    return [game for game, _data in rows]


def _initials(name: str) -> str:
    words = [word for word in name.split() if word[:1].isalnum()]
    return "".join(word[0] for word in words[:2]).upper() or "?"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _downloaded_cover(covers: Iterable[dict[str, Any]]) -> Path | None:
    for cover in covers:
        if cover.get("status") == "downloaded" and cover.get("file_path"):
            path = Path(cover["file_path"])
            if path.is_file():
                return path
    return None


def _open_folder(path: Path) -> None:
    try:
        open_path(path)
    except (OSError, RuntimeError) as exc:
        messagebox.showerror("Unable to open", str(exc))


class LibraryPage:
    """Game Library: browse, filter, sort and annotate games in a list or cover grid."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.library = app.library
        self.user_data = GameUserDataService()
        self.watch = UpdateWatchService()
        self.thumbnails = ThumbnailCache()

        self._games: list[GameSummary] = []
        self._by_id: dict[str, GameSummary] = {}
        self._data: dict[str, GameUserData] = {}
        self._watched: set[str] = set()
        self._visible: list[GameSummary] = []
        self._total_games = 0
        self._loaded = False
        self._closed = False
        self._generation = 0
        self._search_job: str | None = None
        self._notes_job: str | None = None
        self._thumb_job: str | None = None
        self._notes_draft: str | None = None
        self._detail_titleid: str | None = None
        self._detail_name = ""
        self._grid_columns = 0
        self._card_art: dict[str, tuple[int, int]] = {}
        # Worker-thread cover lookups; plain dict get/set is atomic under the GIL.
        self._cover_paths: dict[str, Path | None] = {}
        self._photos: dict[tuple[str, tuple[int, int]], tk.PhotoImage | None] = {}
        self._requested: set[tuple[str, tuple[int, int]]] = set()
        self._thumb_queue: queue.Queue[tuple[str, tuple[int, int]] | None] = queue.Queue()

        self.view = "grid" if read_config().get("library_view") == "grid" else "list"
        self.chip = "All"
        self.descending = False
        self.search_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="Name")
        self.play_filter_var = tk.StringVar(value=ANY_STATUS)
        self.tag_filter_var = tk.StringVar(value=ANY_TAG)

        app._page_header(
            "Game Library",
            "Browse, filter and annotate your games, title updates and cover art.",
        )
        self.body = ttk.Frame(app.content)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.columnconfigure(0, weight=1)
        self.body.columnconfigure(1, minsize=340)
        self.body.rowconfigure(3, weight=1)
        self.body.bind("<Destroy>", self._on_destroy, add="+")

        self._build_metrics()
        self._build_toolbar()
        self._build_bulk_bar()
        self._build_views()
        self._build_details()
        self.search_var.trace_add("write", self._on_search)
        threading.Thread(
            target=self._thumbnail_worker, name="Library thumbnails", daemon=True
        ).start()
        self._update_controls()
        self.refresh()

    # ------------------------------------------------------------ public

    def refresh(self) -> None:
        """Reload games and personal data, keeping filters, sort and selection."""
        if self._closed:
            return
        # Retry games that had no cover last time; covers may have downloaded since.
        for key, photo in list(self._photos.items()):
            if photo is None:
                del self._photos[key]
                self._requested.discard(key)
        for titleid, path in list(self._cover_paths.items()):
            if path is None:
                self._cover_paths.pop(titleid, None)
        self._reload(force_details=True)

    def select(self, titleid: str) -> None:
        """Select a game, clearing filters when it is currently hidden."""
        if self._closed:
            return
        game = self._find(titleid)
        self.app.current_game = game.titleid if game else titleid
        if game is None or game not in self._visible:
            self._clear_filters()  # The reload restores app.current_game.
            return
        if self.view == "list":
            self.tree.selection_set([game.titleid])
            self.tree.focus(game.titleid)
            self.tree.see(game.titleid)
        else:
            self._highlight_card()
            self._scroll_to_card(game.titleid)
        self._show_game(game.titleid)

    # ------------------------------------------------------------ layout

    def _build_metrics(self) -> None:
        metrics = ttk.Frame(self.body)
        metrics.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self._metric_labels: dict[str, ttk.Label] = {}
        for index, label in enumerate(("Games", "Favorites", "Updates downloaded", "Failed")):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=(14, 6))
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 12, 0))
            card.columnconfigure(0, weight=1)
            metrics.columnconfigure(index, weight=1, uniform="metric")
            # Label and number share one row so the cards leave height for the detail pane.
            ttk.Label(card, text=label, style="CardMuted.TLabel").grid(
                row=0, column=0, sticky=tk.W
            )
            value = ttk.Label(card, text="—", style="Metric.TLabel")
            value.grid(row=0, column=1, sticky=tk.E, padx=(8, 0))
            self._metric_labels[label] = value

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.body)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        bar.columnconfigure(0, weight=1)

        top = ttk.Frame(bar)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="Search", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 8))
        search = ttk.Entry(top, textvariable=self.search_var)
        search.grid(row=0, column=1, sticky="ew")
        search.bind("<Escape>", lambda _event: self.search_var.set(""))
        ttk.Label(top, text="Sort", style="Muted.TLabel").grid(row=0, column=2, padx=(16, 8))
        sort_box = ttk.Combobox(
            top, textvariable=self.sort_var, values=SORT_KEYS, state="readonly", width=13
        )
        sort_box.grid(row=0, column=3)
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self._render())
        self.direction_button = ttk.Button(top, width=8, command=self._toggle_direction)
        self.direction_button.grid(row=0, column=4, padx=(6, 0))
        self.view_buttons: dict[str, ttk.Button] = {}
        for column, (view, text) in enumerate((("list", "List"), ("grid", "Grid")), start=5):
            button = ttk.Button(top, text=text, command=lambda value=view: self._set_view(value))
            button.grid(row=0, column=column, padx=(16 if view == "list" else 4, 0))
            self.view_buttons[view] = button
        ttk.Button(top, text="Refresh", command=self.refresh).grid(
            row=0, column=7, padx=(16, 0)
        )

        filters = ttk.Frame(bar)
        filters.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.chip_buttons: dict[str, ttk.Button] = {}
        for chip in CHIPS:
            button = ttk.Button(
                filters, text=chip, command=lambda value=chip: self._set_chip(value)
            )
            button.pack(side=tk.LEFT, padx=(0, 6))
            self.chip_buttons[chip] = button
        self.tag_box = ttk.Combobox(
            filters, textvariable=self.tag_filter_var, values=(ANY_TAG,),
            state="readonly", width=16,
        )
        self.tag_box.pack(side=tk.RIGHT)
        self.tag_box.bind("<<ComboboxSelected>>", lambda _event: self._render())
        ttk.Label(filters, text="Tag", style="Muted.TLabel").pack(side=tk.RIGHT, padx=(12, 6))
        play_box = ttk.Combobox(
            filters, textvariable=self.play_filter_var,
            values=(ANY_STATUS, NO_STATUS, *PLAY_STATUSES[1:]), state="readonly", width=12,
        )
        play_box.pack(side=tk.RIGHT)
        play_box.bind("<<ComboboxSelected>>", lambda _event: self._render())
        ttk.Label(filters, text="Play status", style="Muted.TLabel").pack(
            side=tk.RIGHT, padx=(12, 6)
        )

    def _build_bulk_bar(self) -> None:
        self.bulk_bar = ttk.Frame(self.body, style="Card.TFrame", padding=(12, 8))
        self.bulk_bar.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.bulk_label = ttk.Label(self.bulk_bar, style="CardHeading.TLabel")
        self.bulk_label.pack(side=tk.LEFT, padx=(0, 12))
        actions: tuple[tuple[str, Callable[[], None]], ...] = (
            ("Favorite", lambda: self._bulk_favorite(True)),
            ("Unfavorite", lambda: self._bulk_favorite(False)),
            ("Add tag…", self._bulk_add_tag),
        )
        for text, command in actions:
            ttk.Button(self.bulk_bar, text=text, style="Ghost.TButton", command=command).pack(
                side=tk.LEFT, padx=(0, 4)
            )
        status_button = ttk.Menubutton(self.bulk_bar, text="Set status ▾")
        menu = tk.Menu(
            status_button, tearoff=False, background=PALETTE.panel_alt,
            foreground=PALETTE.text, activebackground=PALETTE.selection,
            activeforeground=PALETTE.selection_text,
        )
        for status in PLAY_STATUSES:
            menu.add_command(
                label=status or NO_STATUS, command=lambda value=status: self._bulk_status(value)
            )
        status_button.configure(menu=menu)
        status_button.pack(side=tk.LEFT, padx=(0, 4))
        for text, command in (
            ("Watch updates", lambda: self._bulk_watch(True)),
            ("Unwatch", lambda: self._bulk_watch(False)),
        ):
            ttk.Button(self.bulk_bar, text=text, style="Ghost.TButton", command=command).pack(
                side=tk.LEFT, padx=(0, 4)
            )
        ttk.Button(
            self.bulk_bar, text="Export selection", style="Accent.TButton",
            command=self._export_selection,
        ).pack(side=tk.RIGHT)
        self.bulk_bar.grid_remove()

    def _build_views(self) -> None:
        views = ttk.Frame(self.body)
        views.grid(row=3, column=0, sticky="nsew")
        views.columnconfigure(0, weight=1)
        views.rowconfigure(0, weight=1)

        self.list_frame = ttk.Frame(views)
        self.list_frame.grid(row=0, column=0, sticky="nsew")
        self.list_frame.columnconfigure(0, weight=1)
        self.list_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            self.list_frame,
            columns=[column[0] for column in TREE_COLUMNS],
            show="headings",
            selectmode="extended",
        )
        for column, heading, width, anchor, stretch, _key in TREE_COLUMNS:
            self.tree.heading(
                column, text=heading, command=lambda value=column: self._sort_by_column(value)
            )
            self.tree.column(
                column, width=width, minwidth=width if stretch else 24, anchor=anchor,
                stretch=stretch,
            )
        self.tree.tag_configure("odd", background=PALETTE.panel_alt)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        tree_scroll = ttk.Scrollbar(self.list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        # Narrow windows cannot fit every fixed-width column; scroll instead of clipping.
        tree_xscroll = ttk.Scrollbar(
            self.list_frame, orient=tk.HORIZONTAL, command=self.tree.xview
        )
        tree_xscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=tree_scroll.set, xscrollcommand=tree_xscroll.set)

        self.grid_frame = ttk.Frame(views)
        self.grid_frame.grid(row=0, column=0, sticky="nsew")
        self.grid_frame.columnconfigure(0, weight=1)
        self.grid_frame.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            self.grid_frame, background=PALETTE.panel, highlightthickness=0, borderwidth=0,
            yscrollincrement=20,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        grid_scroll = ttk.Scrollbar(self.grid_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        grid_scroll.grid(row=0, column=1, sticky="ns")

        def on_scroll(first: str, last: str) -> None:
            grid_scroll.set(first, last)
            self._schedule_thumbnails()

        self.canvas.configure(yscrollcommand=on_scroll)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<Button-1>", self._on_card_click)
        self.canvas.bind("<Double-Button-1>", self._on_card_double_click)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.bind(sequence, self._on_wheel)

        self.empty_frame = ttk.Frame(views, padding=32)
        self.empty_frame.grid(row=0, column=0, sticky="nsew")
        self.empty_title = ttk.Label(self.empty_frame, style="Section.TLabel")
        self.empty_title.pack(pady=(48, 4))
        self.empty_hint = ttk.Label(self.empty_frame, style="Muted.TLabel")
        self.empty_hint.pack(pady=(0, 16))
        self.empty_button = ttk.Button(self.empty_frame, style="Accent.TButton")
        self.empty_button.pack()

        for frame in (self.list_frame, self.grid_frame, self.empty_frame):
            frame.grid_remove()

    def _build_details(self) -> None:
        pane = ttk.Frame(self.body, style="Card.TFrame", padding=12)
        pane.grid(row=2, column=1, rowspan=2, sticky="nsew", padx=(16, 0))
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        self.detail_empty = ttk.Label(pane, text="Loading library…", style="CardMuted.TLabel")
        self.detail_empty.grid(row=0, column=0, sticky="n", pady=24)

        body = self.detail_body = ttk.Frame(pane, style="Card.TFrame")
        body.grid(row=0, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)  # Only the notebook shrinks when space runs out.

        top = ttk.Frame(body, style="Card.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)
        self.detail_art = tk.Canvas(
            top, width=DETAIL_ART[0], height=DETAIL_ART[1], background=PALETTE.panel_alt,
            highlightthickness=0, borderwidth=0,
        )
        self.detail_art.grid(row=0, column=0, sticky="nw", padx=(0, 12))
        info = ttk.Frame(top, style="Card.TFrame")
        info.grid(row=0, column=1, sticky="nsew")
        self.detail_title = ttk.Label(info, style="CardHeading.TLabel", wraplength=210)
        self.detail_title.pack(anchor=tk.W)
        self.detail_publisher = ttk.Label(info, style="CardMuted.TLabel", wraplength=210)
        self.detail_publisher.pack(anchor=tk.W, pady=(2, 2))
        id_row = ttk.Frame(info, style="Card.TFrame")
        id_row.pack(anchor=tk.W, fill=tk.X)
        self.detail_titleid = ttk.Label(id_row, style="Card.TLabel")
        self.detail_titleid.pack(side=tk.LEFT)
        ttk.Button(
            id_row, text="Copy", style="Ghost.TButton", command=self._copy_titleid
        ).pack(side=tk.LEFT, padx=(6, 0))
        status_row = ttk.Frame(info, style="Card.TFrame")
        status_row.pack(anchor=tk.W, fill=tk.X, pady=(2, 0))
        self.favorite_button = ttk.Button(
            status_row, style="Ghost.TButton", command=self._toggle_favorite
        )
        self.favorite_button.pack(side=tk.LEFT)
        self.play_var = tk.StringVar()
        play_box = ttk.Combobox(
            status_row, textvariable=self.play_var, values=(NO_STATUS, *PLAY_STATUSES[1:]),
            state="readonly", width=11,
        )
        play_box.pack(side=tk.LEFT, padx=(6, 0))
        play_box.bind("<<ComboboxSelected>>", lambda _event: self._set_play_status())
        self.notebook = ttk.Notebook(body)
        self.notebook.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        personal = ttk.Frame(self.notebook, padding=8)
        personal.columnconfigure(0, weight=1)
        self.notebook.add(personal, text="Details")
        stars = ttk.Frame(personal)
        stars.grid(row=0, column=0, sticky=tk.W, pady=(0, 4))
        ttk.Label(stars, text="Rating", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 6))
        self.star_buttons = []
        for value in range(1, 6):
            button = ttk.Button(
                stars, text="☆", width=2, style="Tool.TButton",
                command=lambda rating=value: self._set_rating(rating),
            )
            button.pack(side=tk.LEFT)
            self.star_buttons.append(button)
        self.watch_var = tk.BooleanVar()
        ttk.Checkbutton(
            personal, text="Watch for new title updates", variable=self.watch_var,
            command=self._toggle_watch,
        ).grid(row=1, column=0, sticky=tk.W, pady=(0, 6))
        tags = ttk.Frame(personal)
        tags.grid(row=2, column=0, sticky="ew")
        tags.columnconfigure(0, weight=1)
        self.tags_frame = ttk.Frame(tags)
        self.tags_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.tag_entry_var = tk.StringVar()
        tag_entry = ttk.Entry(tags, textvariable=self.tag_entry_var, width=12)
        tag_entry.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        tag_entry.bind("<Return>", lambda _event: self._add_tag())
        ttk.Button(tags, text="Add tag", command=self._add_tag).grid(
            row=1, column=1, padx=(6, 0), pady=(4, 0)
        )
        # Notes get their own tab so they keep a usable height at the minimum window size.
        notes_tab = ttk.Frame(self.notebook, padding=8)
        notes_tab.columnconfigure(0, weight=1)
        notes_tab.rowconfigure(0, weight=1)
        self.notebook.add(notes_tab, text="Notes")
        # width=1: the grid stretches it; Text's default 80 columns would widen the pane.
        self.notes = tk.Text(notes_tab, width=1, height=3, wrap=tk.WORD, **text_options())
        self.notes.grid(row=0, column=0, sticky="nsew")
        self.notes.bind("<KeyRelease>", self._on_notes_edit)
        self.notes.bind("<FocusOut>", lambda _event: self._flush_notes())
        self.updates_tree = self._detail_tree(
            "Title Updates",
            ("media_id", "version", "status", "size"),
            ("MediaID", "Version", "Status", "Size"),
        )
        self.covers_tree = self._detail_tree(
            "Covers",
            ("type", "resolution", "status", "size"),
            ("Type", "Resolution", "Status", "Size"),
        )

        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            buttons, text="Open Download Folder", command=lambda: _open_folder(DOWNLOADS_DIR)
        ).pack(side=tk.LEFT)
        ttk.Button(
            buttons, text="Open Advanced Tools", command=self.app._open_legacy_gui
        ).pack(side=tk.RIGHT)
        body.grid_remove()

    def _detail_tree(
        self, tab_name: str, columns: tuple[str, ...], headings: tuple[str, ...]
    ) -> ttk.Treeview:
        frame = ttk.Frame(self.notebook, padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.notebook.add(frame, text=tab_name)
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=4)
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=70, minwidth=50, anchor=tk.CENTER)
        tree.grid(row=0, column=0, sticky="nsew")
        return tree

    # -------------------------------------------------------------- data

    def _reload(self, force_details: bool = False) -> None:
        self._search_job = None
        self._generation += 1
        generation = self._generation
        search = self.search_var.get()

        def work() -> tuple[Any, ...]:
            counts = self.library.get_dashboard_counts()
            games = self.library.list_games(search)
            return (
                counts,
                games,
                self.user_data.get_many(game.titleid for game in games),
                {titleid.upper() for titleid in self.watch.watched_titleids()},
                self.user_data.all_tags(),
                self.user_data.favorite_count(),
            )

        def done(result: tuple[Any, ...]) -> None:
            if self._closed or generation != self._generation:
                return
            counts, games, data, watched, tags, favorites = result
            self._games = games
            self._by_id = {game.titleid: game for game in games}
            self._data = data
            self._watched = watched
            self._total_games = int(counts["games"])
            self._loaded = True
            self._metric_labels["Games"].configure(text=f"{self._total_games:,}")
            self._metric_labels["Favorites"].configure(text=f"{favorites:,}")
            self._metric_labels["Updates downloaded"].configure(
                text=f"{counts['updates_downloaded']:,} / {counts['updates_available']:,}"
            )
            self._metric_labels["Failed"].configure(text=f"{counts['failed']:,}")
            self._set_tag_choices(tags)
            if force_details:
                self._flush_notes()
                self._detail_titleid = None
            self._render()

        self.app.run_background("Loading library", work, done)

    def _set_tag_choices(self, tags: list[tuple[str, int]]) -> None:
        names = [tag for tag, _count in tags]
        self.tag_box.configure(values=(ANY_TAG, *names))
        current = self.tag_filter_var.get().casefold()
        if current != ANY_TAG.casefold() and current not in {name.casefold() for name in names}:
            self.tag_filter_var.set(ANY_TAG)

    def _user(self, titleid: str) -> GameUserData:
        key = titleid.upper()
        return self._data.get(key) or GameUserData(key)

    def _find(self, titleid: str) -> GameSummary | None:
        wanted = titleid.upper()
        return next((game for game in self._games if game.titleid.upper() == wanted), None)

    def _apply(self, titleids: list[str], action: Callable[[], object]) -> bool:
        """Run a personal-data write, then refresh what it affects."""
        try:
            action()
        except ValueError as exc:
            self.app.notify("warning", "Not saved", str(exc), source="Library")
            self._fill_personal()  # Revert detail widgets to the stored values.
            return False
        except sqlite3.Error as exc:
            self.app.notify("error", "Could not save game data", str(exc), source="Library")
            self._fill_personal()
            return False
        self._data.update(self.user_data.get_many(titleids))
        self._set_tag_choices(self.user_data.all_tags())
        self._metric_labels["Favorites"].configure(text=f"{self.user_data.favorite_count():,}")
        self._render()
        self._fill_personal()
        return True

    # ----------------------------------------------------------- filters

    def _on_search(self, *_args: object) -> None:
        if self._search_job is not None:
            self.body.after_cancel(self._search_job)
        self._search_job = self.body.after(200, self._reload)

    def _set_chip(self, chip: str) -> None:
        self.chip = chip
        self._render()

    def _toggle_direction(self) -> None:
        self.descending = not self.descending
        self._render()

    def _sort_by_column(self, column: str) -> None:
        key = next(entry[5] for entry in TREE_COLUMNS if entry[0] == column)
        if self.sort_var.get() == key:
            self.descending = not self.descending
        else:
            self.sort_var.set(key)
            self.descending = False
        self._render()

    def _set_view(self, view: str) -> None:
        if view == self.view:
            return
        self.view = view
        try:
            update_config({"library_view": view})
        except OSError:
            pass  # A failed preference write must not block switching views.
        self._render()

    def _clear_filters(self) -> None:
        self.chip = "All"
        self.play_filter_var.set(ANY_STATUS)
        self.tag_filter_var.set(ANY_TAG)
        self.search_var.set("")
        if self._search_job is not None:
            self.body.after_cancel(self._search_job)
        self._reload()

    def _update_controls(self) -> None:
        for chip, button in self.chip_buttons.items():
            button.configure(style="ChipActive.TButton" if chip == self.chip else "Chip.TButton")
        for view, button in self.view_buttons.items():
            button.configure(style="ChipActive.TButton" if view == self.view else "Chip.TButton")
        self.direction_button.configure(text="↓ Desc" if self.descending else "↑ Asc")
        arrow = " ▼" if self.descending else " ▲"
        sort_key = self.sort_var.get()
        for column, heading, *_rest, key in TREE_COLUMNS:
            self.tree.heading(column, text=heading + (arrow if key == sort_key else ""))

    # ---------------------------------------------------------- rendering

    def _render(self) -> None:
        self._update_controls()
        if not self._loaded:
            return
        play = self.play_filter_var.get()
        tag = self.tag_filter_var.get()
        self._visible = filter_and_sort(
            self._games,
            self._data,
            self._watched,
            chip=self.chip,
            play_status=None if play == ANY_STATUS else ("" if play == NO_STATUS else play),
            tag=None if tag == ANY_TAG else tag,
            sort_key=self.sort_var.get(),
            descending=self.descending,
        )
        for frame in (self.list_frame, self.grid_frame, self.empty_frame):
            frame.grid_remove()
        if not self._visible:
            self._show_empty()
        elif self.view == "list":
            self.list_frame.grid()
            self._render_tree()
        else:
            self.grid_frame.grid()
            self._render_grid()
        self._update_bulk_bar()

    def _show_empty(self) -> None:
        if self._total_games == 0:
            self.empty_title.configure(text="No games yet")
            self.empty_hint.configure(text="Import TitleIDs to start building your library.")
            self.empty_button.configure(
                text="Add games", command=lambda: self.app.navigate("add_games")
            )
        else:
            self.empty_title.configure(text="No games match these filters")
            self.empty_hint.configure(text="Try a different search or clear the filters.")
            self.empty_button.configure(text="Clear filters", command=self._clear_filters)
        self.empty_frame.grid()
        self._show_game(None)

    def _render_tree(self) -> None:
        tree = self.tree
        keep = list(tree.selection())
        if self.app.current_game not in keep:
            keep = [self.app.current_game] if self.app.current_game else []
        top = tree.yview()[0]
        tree.delete(*tree.get_children())
        for index, game in enumerate(self._visible):
            data = self._user(game.titleid)
            tree.insert(
                "",
                tk.END,
                iid=game.titleid,
                values=(
                    "★" if data.favorite else "",
                    game.name,
                    game.titleid,
                    game.publisher or "—",
                    f"{game.updates_downloaded}/{game.updates_total}",
                    summary_status(game),
                    data.play_status or "—",
                ),
                tags=("odd",) if index % 2 else (),
            )
        tree.yview_moveto(top)
        keep = [titleid for titleid in keep if tree.exists(titleid)] or [self._visible[0].titleid]
        focus = self.app.current_game if self.app.current_game in keep else keep[0]
        tree.selection_set(keep)
        tree.focus(focus)
        tree.see(focus)
        self._show_game(focus)

    def _render_grid(self) -> None:
        canvas = self.canvas
        top = canvas.yview()[0]
        canvas.delete("all")
        self._card_art.clear()
        width = max(canvas.winfo_width(), CARD_W + 2 * CARD_GAP)
        columns = max(1, (width - CARD_GAP) // (CARD_W + CARD_GAP))
        self._grid_columns = columns
        for index, game in enumerate(self._visible):
            row, column = divmod(index, columns)
            x = CARD_GAP + column * (CARD_W + CARD_GAP)
            y = CARD_GAP + row * (CARD_H + CARD_GAP)
            tag = f"card:{game.titleid}"
            canvas.create_rectangle(
                x, y, x + CARD_W, y + CARD_H, fill=PALETTE.panel_alt, outline=PALETTE.border,
                tags=(tag, "frame", f"{tag}:frame"),
            )
            art_x, art_y = x + CARD_PAD, y + CARD_PAD
            self._card_art[game.titleid] = (art_x, art_y)
            self._draw_art(
                canvas, art_x, art_y, GRID_ART, game.name,
                self._photos.get((game.titleid, GRID_ART)), tag,
            )
            if self._user(game.titleid).favorite:
                canvas.create_text(
                    art_x + GRID_ART[0] - 6, art_y + 4, anchor=tk.NE, text="★",
                    fill=PALETTE.warning, font=font("large", "bold"), tags=(tag, f"{tag}:star"),
                )
            text_y = art_y + GRID_ART[1] + 10
            canvas.create_text(
                art_x, text_y, anchor=tk.NW, text=_truncate(game.name, 22),
                fill=PALETTE.text, font=font("base", "bold"), tags=(tag,),
            )
            canvas.create_text(
                art_x, text_y + 22, anchor=tk.NW,
                text=f"{summary_status(game)} · {game.updates_downloaded}/{game.updates_total}",
                fill=PALETTE.muted, font=font("small"), tags=(tag,),
            )
        rows = -(-len(self._visible) // columns)
        canvas.configure(scrollregion=(0, 0, width, CARD_GAP + rows * (CARD_H + CARD_GAP)))
        canvas.yview_moveto(top)
        current = self._find(self.app.current_game or "")
        if current is None or current not in self._visible:
            current = self._visible[0]
        self.app.current_game = current.titleid
        self._highlight_card()
        self._show_game(current.titleid)
        self._schedule_thumbnails()

    def _draw_art(
        self,
        canvas: tk.Canvas,
        x: int,
        y: int,
        size: tuple[int, int],
        name: str,
        photo: tk.PhotoImage | None,
        tag: str,
    ) -> None:
        width, height = size
        canvas.create_rectangle(
            x, y, x + width - 1, y + height - 1, fill=PALETTE.panel_alt,
            outline=PALETTE.border, tags=(tag,),
        )
        if photo is not None:
            canvas.create_image(x, y, anchor=tk.NW, image=photo, tags=(tag,))
        else:
            canvas.create_text(
                x + width // 2, y + height // 2, text=_initials(name), fill=PALETTE.muted,
                font=font("title", "bold"), tags=(tag, f"{tag}:placeholder"),
            )

    def _highlight_card(self) -> None:
        self.canvas.itemconfigure("frame", outline=PALETTE.border, width=1)
        if self.app.current_game:
            self.canvas.itemconfigure(
                f"card:{self.app.current_game}:frame", outline=PALETTE.accent, width=2
            )

    def _scroll_to_card(self, titleid: str) -> None:
        position = self._card_art.get(titleid)
        region = self.canvas.cget("scrollregion").split()
        if position is None or len(region) != 4:
            return
        total = float(region[3]) or 1.0
        top = self.canvas.canvasy(0)
        bottom = top + self.canvas.winfo_height()
        if not top <= position[1] - CARD_PAD <= bottom - CARD_H:
            self.canvas.yview_moveto(max(0.0, (position[1] - CARD_PAD - CARD_GAP) / total))

    def _update_bulk_bar(self) -> None:
        count = len(self.tree.selection()) if self.view == "list" and self._visible else 0
        if count > 1:
            self.bulk_label.configure(text=f"{count} selected")
            self.bulk_bar.grid()
        else:
            self.bulk_bar.grid_remove()

    # --------------------------------------------------------- selection

    def _on_tree_select(self, _event: tk.Event[Any]) -> None:
        selection = self.tree.selection()
        self._update_bulk_bar()
        if not selection:
            return
        focus = self.tree.focus()
        self._show_game(focus if focus in selection else selection[0])

    def _card_at_pointer(self) -> str | None:
        items = self.canvas.find_withtag("current")
        if not items:
            return None
        for tag in self.canvas.gettags(items[0]):
            if tag.startswith("card:") and ":" not in tag[5:]:
                return tag[5:]
        return None

    def _on_card_click(self, _event: tk.Event[Any]) -> None:
        self.canvas.focus_set()
        titleid = self._card_at_pointer()
        if titleid:
            self.app.current_game = titleid
            self._highlight_card()
            self._show_game(titleid)

    def _on_card_double_click(self, event: tk.Event[Any]) -> None:
        self._on_card_click(event)
        if self._card_at_pointer():
            self.notebook.select(0)
            self.favorite_button.focus_set()

    def _on_wheel(self, event: tk.Event[Any]) -> None:
        if event.num == 4 or getattr(event, "delta", 0) > 0:
            self.canvas.yview_scroll(-3, "units")
        else:
            self.canvas.yview_scroll(3, "units")

    def _on_canvas_resize(self, _event: tk.Event[Any]) -> None:
        if self.view != "grid" or not self._visible:
            return
        columns = max(1, (self.canvas.winfo_width() - CARD_GAP) // (CARD_W + CARD_GAP))
        if columns != self._grid_columns:
            self._render_grid()
        else:
            self._schedule_thumbnails()

    # ------------------------------------------------------------ details

    def _show_game(self, titleid: str | None) -> None:
        if titleid is not None and titleid == self._detail_titleid:
            return
        self._flush_notes()
        self._detail_titleid = titleid
        details = self.library.get_game_details(titleid) if titleid else {}
        if not details:
            self._detail_titleid = None
            self.detail_body.grid_remove()
            self.detail_empty.configure(text="Select a game to see its details.")
            self.detail_empty.grid()
            return
        self.app.current_game = titleid
        title = details["title"]
        game = self._by_id.get(titleid)
        name = game.name if game else str(title.get("name") or "Unknown game")
        self._detail_name = name
        self.detail_title.configure(text=_truncate(name, 24))
        self.detail_publisher.configure(
            text=_truncate(str(title.get("publisher") or "Unknown publisher"), 36)
        )
        self.detail_titleid.configure(text=titleid)
        self.notes.delete("1.0", tk.END)
        self.notes.insert("1.0", self._user(titleid).notes)
        self._notes_draft = None
        self._fill_personal()

        self.updates_tree.delete(*self.updates_tree.get_children())
        for update in details["updates"]:
            self.updates_tree.insert(
                "",
                tk.END,
                values=(
                    update.get("media_id") or "Unknown",
                    update.get("version") or "Unknown",
                    update.get("status") or "pending",
                    format_size(update.get("file_size")),
                ),
            )
        self.covers_tree.delete(*self.covers_tree.get_children())
        for cover in details["covers"]:
            self.covers_tree.insert(
                "",
                tk.END,
                values=(
                    cover.get("cover_type") or "Unknown",
                    cover.get("resolution") or "Unknown",
                    cover.get("status") or "pending",
                    format_size(cover.get("file_size")),
                ),
            )

        self._cover_paths[titleid] = _downloaded_cover(details["covers"])
        self._draw_detail_art()
        self._request_thumbnail(titleid, DETAIL_ART)
        self.detail_empty.grid_remove()
        self.detail_body.grid()

    def _fill_personal(self) -> None:
        titleid = self._detail_titleid
        if titleid is None:
            return
        data = self._user(titleid)
        self.favorite_button.configure(text="★ Favorite" if data.favorite else "☆ Favorite")
        self.play_var.set(data.play_status or NO_STATUS)
        for value, button in enumerate(self.star_buttons, start=1):
            button.configure(text="★" if data.rating and value <= data.rating else "☆")
        self.watch_var.set(titleid.upper() in self._watched)
        for child in self.tags_frame.winfo_children():
            child.destroy()
        if not data.tags:
            ttk.Label(self.tags_frame, text="No tags yet", style="Muted.TLabel").grid(
                row=0, column=0, sticky=tk.W
            )
        for index, tag in enumerate(data.tags):
            ttk.Button(
                self.tags_frame, text=f"{tag}  ×", style="Chip.TButton",
                command=lambda value=tag: self._remove_tag(value),
            ).grid(row=index // 3, column=index % 3, sticky=tk.W, padx=(0, 6), pady=(0, 6))

    def _draw_detail_art(self) -> None:
        self.detail_art.delete("all")
        if self._detail_titleid:
            self._draw_art(
                self.detail_art, 0, 0, DETAIL_ART, self._detail_name,
                self._photos.get((self._detail_titleid, DETAIL_ART)), "art",
            )

    def _copy_titleid(self) -> None:
        if self._detail_titleid:
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(self._detail_titleid)
            self.app.set_status(f"Copied {self._detail_titleid} to the clipboard")

    def _toggle_favorite(self) -> None:
        titleid = self._detail_titleid
        if titleid:
            favorite = not self._user(titleid).favorite
            self._apply([titleid], lambda: self.user_data.set_favorite(titleid, favorite))

    def _set_play_status(self) -> None:
        titleid = self._detail_titleid
        value = self.play_var.get()
        status = "" if value == NO_STATUS else value
        if titleid:
            self._apply([titleid], lambda: self.user_data.set_play_status(titleid, status))

    def _set_rating(self, rating: int) -> None:
        titleid = self._detail_titleid
        if titleid:
            new = None if self._user(titleid).rating == rating else rating
            self._apply([titleid], lambda: self.user_data.set_rating(titleid, new))

    def _add_tag(self) -> None:
        titleid = self._detail_titleid
        tag = self.tag_entry_var.get()
        if titleid and self._apply([titleid], lambda: self.user_data.add_tag(titleid, tag)):
            self.tag_entry_var.set("")

    def _remove_tag(self, tag: str) -> None:
        titleid = self._detail_titleid
        if titleid:
            self._apply([titleid], lambda: self.user_data.remove_tag(titleid, tag))

    def _toggle_watch(self) -> None:
        titleid = self._detail_titleid
        if titleid:
            watched = self.watch_var.get()
            self._apply([titleid], lambda: self._set_watched([titleid], watched))

    def _set_watched(self, titleids: list[str], watched: bool) -> None:
        for titleid in titleids:
            self.watch.set_watched(titleid, watched)
        self._watched = {titleid.upper() for titleid in self.watch.watched_titleids()}

    def _on_notes_edit(self, _event: tk.Event[Any]) -> None:
        self._notes_draft = self.notes.get("1.0", "end-1c")
        if self._notes_job is not None:
            self.body.after_cancel(self._notes_job)
        self._notes_job = self.body.after(600, self._flush_notes)

    def _flush_notes(self) -> None:
        if self._notes_job is not None:
            self.body.after_cancel(self._notes_job)
            self._notes_job = None
        draft, self._notes_draft = self._notes_draft, None
        titleid = self._detail_titleid
        if draft is None or titleid is None or draft == self._user(titleid).notes:
            return
        try:
            self.user_data.set_notes(titleid, draft)
            self._data.update(self.user_data.get_many([titleid]))
        except sqlite3.Error as exc:
            self.app.notify("error", "Could not save notes", str(exc), source="Library")

    # ------------------------------------------------------------- bulk

    def _selected_ids(self) -> list[str]:
        return list(self.tree.selection())

    def _bulk_favorite(self, favorite: bool) -> None:
        ids = self._selected_ids()
        self._apply(ids, lambda: self.user_data.set_favorite_many(ids, favorite))

    def _bulk_add_tag(self) -> None:
        ids = self._selected_ids()
        tag = simpledialog.askstring(
            "Add tag", f"Tag to add to {len(ids)} games:", parent=self.app.root
        )
        if tag is not None:
            self._apply(ids, lambda: self.user_data.add_tag_many(ids, tag))

    def _bulk_status(self, status: str) -> None:
        ids = self._selected_ids()
        self._apply(ids, lambda: self.user_data.set_play_status_many(ids, status))

    def _bulk_watch(self, watched: bool) -> None:
        ids = self._selected_ids()
        self._apply(ids, lambda: self._set_watched(ids, watched))

    def _export_selection(self) -> None:
        ids = set(self._selected_ids())
        games = [game for game in self._visible if game.titleid in ids]
        path = filedialog.asksaveasfilename(
            parent=self.app.root,
            title="Export selection",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialdir=str(EXPORTS_DIR),
            initialfile="library-selection.csv",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ("titleid", "name", "publisher", "updates", "status", "play_status", "tags")
                )
                for game in games:
                    data = self._user(game.titleid)
                    writer.writerow(
                        (
                            game.titleid,
                            game.name,
                            game.publisher,
                            f"{game.updates_downloaded}/{game.updates_total}",
                            summary_status(game),
                            data.play_status,
                            "; ".join(data.tags),
                        )
                    )
        except OSError as exc:
            self.app.notify("error", "Export failed", str(exc), source="Library")
            return
        self.app.notify(
            "success", "Selection exported", f"{len(games)} games saved to {path}",
            source="Library",
        )

    # ---------------------------------------------------------- thumbnails

    def _schedule_thumbnails(self) -> None:
        if self._thumb_job is None and not self._closed:
            self._thumb_job = self.body.after(60, self._request_visible_thumbnails)

    def _request_visible_thumbnails(self) -> None:
        self._thumb_job = None
        if self.view != "grid" or not self._visible or not self._grid_columns:
            return
        stride = CARD_H + CARD_GAP
        top = self.canvas.canvasy(0)
        first_row = max(0, int(top // stride))
        last_row = int((top + self.canvas.winfo_height()) // stride)
        start = first_row * self._grid_columns
        end = (last_row + 1) * self._grid_columns
        for game in self._visible[start:end]:
            self._request_thumbnail(game.titleid, GRID_ART)

    def _request_thumbnail(self, titleid: str, size: tuple[int, int]) -> None:
        key = (titleid, size)
        if key not in self._photos and key not in self._requested:
            self._requested.add(key)
            self._thumb_queue.put(key)

    def _thumbnail_worker(self) -> None:
        while True:
            job = self._thumb_queue.get()
            if job is None or self._closed:
                return
            titleid, size = job
            try:
                if titleid not in self._cover_paths:
                    details = self.library.get_game_details(titleid)
                    self._cover_paths[titleid] = _downloaded_cover(details.get("covers", ()))
                source = self._cover_paths.get(titleid)
                path = self.thumbnails.get(source, size) if source else None
            except Exception:  # One bad cover must not stop the worker thread.
                path = None
            try:
                self.app.root.after(
                    0, lambda t=titleid, s=size, p=path: self._thumbnail_ready(t, s, p)
                )
            except (RuntimeError, tk.TclError):
                return  # The window closed.

    def _thumbnail_ready(self, titleid: str, size: tuple[int, int], path: Path | None) -> None:
        if self._closed:
            return
        photo = None
        if path is not None:
            try:
                photo = tk.PhotoImage(master=self.app.root, file=str(path))
            except tk.TclError:
                photo = None
        self._photos[(titleid, size)] = photo
        if photo is None:
            return
        if size == DETAIL_ART and titleid == self._detail_titleid:
            self._draw_detail_art()
        position = self._card_art.get(titleid)
        if size == GRID_ART and position is not None and self.view == "grid":
            tag = f"card:{titleid}"
            self.canvas.delete(f"{tag}:placeholder")
            self.canvas.create_image(*position, anchor=tk.NW, image=photo, tags=(tag,))
            self.canvas.tag_raise(f"{tag}:star")

    # ------------------------------------------------------------ teardown

    def _on_destroy(self, event: tk.Event[Any]) -> None:
        if event.widget is not self.body:
            return
        self._flush_notes()
        self._closed = True
        self._thumb_queue.put(None)
        for job in (self._search_job, self._thumb_job):
            if job is not None:
                self.body.after_cancel(job)

"""Dark desktop workspace for Xbox 360 profiles and save data."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from gpd_parser import export_gpd_image
from platform_support import open_path
from profile_intelligence import ProfileIntelligenceService
from profile_manager import ProfileSaveManager, mask_identifier
from xenia_bridge import (
    MigrationPlan,
    candidate_xenia_content_roots,
    find_xenia_installation,
    launch_xenia,
)
from ui_theme import PALETTE


def _size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{int(value)} B"


class ProfileSavePage:
    """Profile inventory, save snapshots, and conflict-safe restore UI."""

    def __init__(
        self,
        root: tk.Tk,
        parent: ttk.Frame,
        manager: ProfileSaveManager,
        page_header: Callable[[str, str], None],
        config_path: Path,
    ) -> None:
        self.root = root
        self.parent = parent
        self.manager = manager
        self.intelligence = ProfileIntelligenceService(manager.db_path, manager)
        self.config_path = config_path
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.running = False
        self.profiles: dict[str, dict[str, Any]] = {}
        self.saves: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}
        self.gpd_files: dict[str, dict[str, Any]] = {}
        self.profile_choices: dict[str, str] = {}
        self.migration_plan: MigrationPlan | None = None

        page_header(
            "Profiles & Saves",
            "Inventory, verify, back up, and restore your Xbox 360 profile data.",
        )
        self._build()
        self.refresh()

    def _build(self) -> None:
        body = ttk.Frame(self.parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        config = self._read_config()
        profile_config = config.get("profiles", {})
        if not isinstance(profile_config, dict):
            profile_config = {}
        self.source_var = tk.StringVar(
            value=str(profile_config.get("source_root", ""))
        )
        self.search_var = tk.StringVar()
        self.reveal_var = tk.BooleanVar(value=False)

        controls = ttk.Frame(body)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Content source").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(controls, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(controls, text="Browse", command=self.choose_source).grid(
            row=0, column=2, padx=(0, 8)
        )
        ttk.Button(
            controls,
            text="Scan",
            style="Accent.TButton",
            command=self.scan,
        ).grid(row=0, column=3)

        notebook = ttk.Notebook(body)
        notebook.grid(row=1, column=0, sticky="nsew")

        inventory = ttk.Frame(notebook, padding=10)
        snapshots = ttk.Frame(notebook, padding=10)
        achievements = ttk.Frame(notebook, padding=10)
        history = ttk.Frame(notebook, padding=10)
        compare = ttk.Frame(notebook, padding=10)
        xenia = ttk.Frame(notebook, padding=10)
        notebook.add(inventory, text="Inventory")
        notebook.add(snapshots, text="Snapshots")
        notebook.add(achievements, text="Achievements")
        notebook.add(history, text="Played Titles")
        notebook.add(compare, text="Compare")
        notebook.add(xenia, text="Xenia")
        self._build_inventory(inventory)
        self._build_snapshots(snapshots)
        self._build_achievements(achievements)
        self._build_history(history)
        self._build_compare(compare)
        self._build_xenia(xenia)

        self.status_var = tk.StringVar(value="Choose a Content folder to begin.")
        ttk.Label(body, textvariable=self.status_var, style="Subheader.TLabel").grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

    def _build_inventory(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(toolbar, text="Find saves").pack(side=tk.LEFT)
        search = ttk.Entry(toolbar, textvariable=self.search_var, width=34)
        search.pack(side=tk.LEFT, padx=(8, 14))
        search.bind("<KeyRelease>", lambda _event: self._refresh_saves())
        ttk.Checkbutton(
            toolbar,
            text="Reveal profile identifiers",
            variable=self.reveal_var,
            command=self._refresh_profiles,
        ).pack(side=tk.LEFT)
        ttk.Button(toolbar, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

        panes = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        panes.grid(row=1, column=0, sticky="nsew")

        profile_frame = ttk.LabelFrame(panes, text="Profiles", padding=6)
        save_frame = ttk.LabelFrame(panes, text="Save Data", padding=6)
        panes.add(profile_frame, weight=2)
        panes.add(save_frame, weight=3)
        profile_frame.columnconfigure(0, weight=1)
        profile_frame.rowconfigure(0, weight=1)
        save_frame.columnconfigure(0, weight=1)
        save_frame.rowconfigure(0, weight=1)

        self.profile_tree = ttk.Treeview(
            profile_frame,
            columns=("profile", "saves", "size", "status"),
            show="headings",
            selectmode="browse",
        )
        for column, text, width in (
            ("profile", "Profile", 190),
            ("saves", "Saves", 60),
            ("size", "Size", 80),
            ("status", "Status", 110),
        ):
            self.profile_tree.heading(column, text=text)
            self.profile_tree.column(column, width=width, anchor=tk.W)
        self.profile_tree.grid(row=0, column=0, sticky="nsew")
        self.profile_tree.bind("<<TreeviewSelect>>", self._profile_selected)
        profile_scroll = ttk.Scrollbar(
            profile_frame,
            orient=tk.VERTICAL,
            command=self.profile_tree.yview,
        )
        profile_scroll.grid(row=0, column=1, sticky="ns")
        self.profile_tree.configure(yscrollcommand=profile_scroll.set)

        self.save_tree = ttk.Treeview(
            save_frame,
            columns=("game", "titleid", "size", "status", "modified"),
            show="headings",
            selectmode="extended",
        )
        for column, text, width in (
            ("game", "Game / Save", 230),
            ("titleid", "TitleID", 90),
            ("size", "Size", 80),
            ("status", "Status", 120),
            ("modified", "Modified", 145),
        ):
            self.save_tree.heading(column, text=text)
            self.save_tree.column(column, width=width, anchor=tk.W)
        self.save_tree.grid(row=0, column=0, sticky="nsew")
        self.save_tree.bind("<<TreeviewSelect>>", self._save_selected)
        save_scroll = ttk.Scrollbar(
            save_frame,
            orient=tk.VERTICAL,
            command=self.save_tree.yview,
        )
        save_scroll.grid(row=0, column=1, sticky="ns")
        self.save_tree.configure(yscrollcommand=save_scroll.set)

        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(
            actions,
            text="Back Up Profile",
            command=self.snapshot_profile,
            style="Accent.TButton",
        ).pack(side=tk.LEFT)
        ttk.Button(
            actions,
            text="Back Up Selected Saves",
            command=self.snapshot_saves,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions,
            text="Open Source",
            command=self.open_selected_source,
        ).pack(side=tk.LEFT, padx=(8, 0))
        self.detail_var = tk.StringVar(value="Select a profile or save for details.")
        ttk.Label(
            parent,
            textvariable=self.detail_var,
            style="Subheader.TLabel",
            wraplength=900,
            justify=tk.LEFT,
        ).grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def _build_snapshots(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.snapshot_tree = ttk.Treeview(
            parent,
            columns=("id", "label", "profile", "created", "files", "size", "status"),
            show="headings",
            selectmode="browse",
        )
        for column, text, width in (
            ("id", "ID", 55),
            ("label", "Label", 190),
            ("profile", "Profile", 140),
            ("created", "Created", 170),
            ("files", "Files", 65),
            ("size", "Size", 90),
            ("status", "Status", 90),
        ):
            self.snapshot_tree.heading(column, text=text)
            self.snapshot_tree.column(column, width=width, anchor=tk.W)
        self.snapshot_tree.grid(row=0, column=0, sticky="nsew")
        snapshot_scroll = ttk.Scrollbar(
            parent,
            orient=tk.VERTICAL,
            command=self.snapshot_tree.yview,
        )
        snapshot_scroll.grid(row=0, column=1, sticky="ns")
        self.snapshot_tree.configure(yscrollcommand=snapshot_scroll.set)

        actions = ttk.Frame(parent)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(
            actions,
            text="Restore to Folder",
            command=self.restore_snapshot,
            style="Accent.TButton",
        ).pack(side=tk.LEFT)
        ttk.Button(
            actions,
            text="Export Manifest",
            command=self.export_manifest,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions,
            text="Open Snapshot",
            command=self.open_snapshot,
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="Refresh", command=self.refresh).pack(side=tk.RIGHT)

    def _build_achievements(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=2)
        parent.rowconfigure(3, weight=3)
        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(
            controls,
            text="Import GPD",
            command=self.import_gpd,
            style="Accent.TButton",
        ).pack(side=tk.LEFT)
        ttk.Button(
            controls,
            text="Scan Extracted Folder",
            command=self.scan_gpd_folder,
        ).pack(side=tk.LEFT, padx=(8, 0))
        self.achievement_search_var = tk.StringVar()
        ttk.Label(controls, text="Find").pack(side=tk.LEFT, padx=(20, 6))
        search = ttk.Entry(
            controls, textvariable=self.achievement_search_var, width=28
        )
        search.pack(side=tk.LEFT)
        search.bind("<KeyRelease>", lambda _event: self._refresh_achievements())

        self.gpd_tree = ttk.Treeview(
            parent,
            columns=("titleid", "earned", "score", "status", "path"),
            show="headings",
            selectmode="browse",
            height=6,
        )
        for column, label, width in (
            ("titleid", "TitleID", 90),
            ("earned", "Unlocked", 90),
            ("score", "Gamerscore", 110),
            ("status", "Status", 85),
            ("path", "Extracted GPD", 430),
        ):
            self.gpd_tree.heading(column, text=label)
            self.gpd_tree.column(column, width=width, anchor=tk.W)
        self.gpd_tree.grid(row=1, column=0, sticky="nsew")
        self.gpd_tree.bind(
            "<<TreeviewSelect>>", lambda _event: self._refresh_achievements()
        )

        ttk.Label(
            parent,
            text=(
                "Read-only achievement records from standalone or extracted XDBF/GPD "
                "files. UnityScraper never edits these databases."
            ),
            style="Subheader.TLabel",
        ).grid(row=2, column=0, sticky="ew", pady=(8, 6))
        self.achievement_tree = ttk.Treeview(
            parent,
            columns=("id", "title", "score", "state", "unlocked"),
            show="headings",
        )
        for column, label, width in (
            ("id", "ID", 65),
            ("title", "Achievement", 330),
            ("score", "G", 55),
            ("state", "State", 125),
            ("unlocked", "Unlocked", 180),
        ):
            self.achievement_tree.heading(column, text=label)
            self.achievement_tree.column(column, width=width, anchor=tk.W)
        self.achievement_tree.grid(row=3, column=0, sticky="nsew")

    def _build_compare(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(5, weight=1)
        self.compare_left_var = tk.StringVar()
        self.compare_right_var = tk.StringVar()
        ttk.Label(parent, text="First profile").grid(row=0, column=0, sticky=tk.W)
        self.compare_left = ttk.Combobox(
            parent, textvariable=self.compare_left_var, state="readonly"
        )
        self.compare_left.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(parent, text="Second profile").grid(
            row=1, column=0, sticky=tk.W, pady=(8, 0)
        )
        self.compare_right = ttk.Combobox(
            parent, textvariable=self.compare_right_var, state="readonly"
        )
        self.compare_right.grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        ttk.Button(
            parent,
            text="Compare Profiles",
            command=self.compare_profiles,
            style="Accent.TButton",
        ).grid(row=2, column=1, sticky=tk.W, pady=10)
        self.compare_text = tk.Text(
            parent,
            wrap=tk.WORD,
            background=PALETTE.field,
            foreground=PALETTE.text,
            insertbackground=PALETTE.accent_hot,
            relief=tk.FLAT,
            padx=12,
            pady=10,
        )
        self.compare_text.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.compare_text.insert(
            tk.END,
            "Choose two indexed profiles to compare saves and imported achievements.",
        )
        self.compare_text.configure(state=tk.DISABLED)

    def _build_history(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(3, weight=1)
        self.history_summary_var = tk.StringVar(
            value="Import an extracted dashboard GPD to view played-title history."
        )
        ttk.Label(parent, textvariable=self.history_summary_var,
                  style="Subheader.TLabel").grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.history_tree = ttk.Treeview(
            parent,
            columns=("game", "titleid", "achievements", "score", "last_played"),
            show="headings",
        )
        for column, label, width in (
            ("game", "Game", 300), ("titleid", "TitleID", 90),
            ("achievements", "Achievements", 110), ("score", "Gamerscore", 110),
            ("last_played", "Last Played", 190),
        ):
            self.history_tree.heading(column, text=label)
            self.history_tree.column(column, width=width, anchor=tk.W)
        self.history_tree.grid(row=1, column=0, sticky="nsew")
        image_toolbar = ttk.Frame(parent)
        image_toolbar.grid(row=2, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(image_toolbar, text="Embedded artwork", style="CardTitle.TLabel").pack(
            side=tk.LEFT
        )
        ttk.Button(
            image_toolbar, text="Export Selected Image", command=self.export_embedded_image
        ).pack(side=tk.RIGHT)
        self.gpd_image_tree = ttk.Treeview(
            parent, columns=("format", "size", "source"), show="headings", height=5
        )
        for column, label, width in (
            ("format", "Format", 90), ("size", "Size", 90), ("source", "Source GPD", 620)
        ):
            self.gpd_image_tree.heading(column, text=label)
            self.gpd_image_tree.column(column, width=width, anchor=tk.W)
        self.gpd_image_tree.grid(row=3, column=0, sticky="nsew")
        self.gpd_images: dict[str, dict[str, Any]] = {}

    def export_embedded_image(self) -> None:
        selection = self.gpd_image_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Embedded artwork", "Select an image first.", parent=self.root
            )
            return
        row = self.gpd_images[selection[0]]
        suffix = ".jpg" if row["image_format"] == "jpeg" else f".{row['image_format']}"
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export embedded artwork",
            defaultextension=suffix,
            initialfile=f"gpd-image-{row['entry_id']}{suffix}",
        )
        if not destination:
            return
        try:
            exported = export_gpd_image(row["source_path"], int(row["entry_id"]), destination)
        except Exception as exc:
            messagebox.showerror("Image export failed", str(exc), parent=self.root)
            return
        messagebox.showinfo(
            "Embedded artwork", f"Exported to {exported}", parent=self.root
        )

    def _build_xenia(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(3, weight=1)
        candidates = [str(path) for path in candidate_xenia_content_roots()]
        self.xenia_root_var = tk.StringVar(value=candidates[0] if candidates else "")
        self.xenia_target_var = tk.StringVar()
        self.xenia_game_var = tk.StringVar()
        self.xenia_fullscreen_var = tk.BooleanVar(value=False)
        ttk.Label(parent, text="Xenia folder or content root").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(parent, textvariable=self.xenia_root_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(parent, text="Browse", command=self.choose_xenia_root).grid(
            row=0, column=2
        )
        ttk.Label(parent, text="Target profile ID").grid(
            row=1, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(parent, textvariable=self.xenia_target_var).grid(
            row=1, column=1, sticky="ew", padx=8, pady=(8, 0)
        )
        ttk.Label(parent, text="Game image, folder, or default.xex").grid(
            row=2, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Entry(parent, textvariable=self.xenia_game_var).grid(
            row=2, column=1, sticky="ew", padx=8, pady=(8, 0)
        )
        ttk.Button(parent, text="Browse", command=self.choose_xenia_game).grid(
            row=2, column=2, pady=(8, 0)
        )
        controls = ttk.Frame(parent)
        controls.grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Button(
            controls,
            text="Preview Migration",
            command=self.preview_xenia_migration,
            style="Accent.TButton",
        ).pack(side=tk.LEFT)
        self.xenia_execute_button = ttk.Button(
            controls,
            text="Create Snapshot and Migrate",
            command=self.execute_xenia_migration,
            state=tk.DISABLED,
        )
        self.xenia_execute_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(
            controls, text="Fullscreen", variable=self.xenia_fullscreen_var
        ).pack(side=tk.LEFT, padx=(18, 4))
        ttk.Button(controls, text="Launch Game", command=self.launch_xenia_game).pack(
            side=tk.LEFT
        )
        self.migration_tree = ttk.Treeview(
            parent,
            columns=("titleid", "file", "action", "reason"),
            show="headings",
        )
        for column, label, width in (
            ("titleid", "TitleID", 90),
            ("file", "Save", 300),
            ("action", "Action", 80),
            ("reason", "Reason", 320),
        ):
            self.migration_tree.heading(column, text=label)
            self.migration_tree.column(column, width=width, anchor=tk.W)
        self.migration_tree.grid(row=5, column=0, columnspan=3, sticky="nsew")
        ttk.Label(
            parent,
            text=(
                "Migration is previewed first. A verified save snapshot is created "
                "before any copy, and different destination files are never overwritten."
            ),
            style="Subheader.TLabel",
            wraplength=900,
        ).grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))

    def choose_source(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            title="Choose Xbox 360 Content folder",
        )
        if selected:
            self.source_var.set(selected)
            self._save_source()

    def scan(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            messagebox.showerror(
                "Profiles & Saves",
                "Choose an Xbox 360 Content folder first.",
                parent=self.root,
            )
            return
        self._save_source()
        self._run(
            "Scanning profiles and hashing save packages...",
            lambda: self.manager.scan(source),
            "scan-complete",
        )

    def import_gpd(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Choose an extracted Xbox 360 GPD",
            filetypes=(("GPD databases", "*.gpd"), ("All files", "*.*")),
        )
        if not path:
            return
        profile_id = self._selected_profile_id()
        self._run(
            "Reading the GPD database...",
            lambda: self.intelligence.import_gpd(path, profile_id=profile_id),
            "gpd-complete",
        )

    def scan_gpd_folder(self) -> None:
        path = filedialog.askdirectory(
            parent=self.root,
            title="Choose a folder containing extracted GPD files",
        )
        if not path:
            return
        profile_id = self._selected_profile_id()
        self._run(
            "Finding and reading extracted GPD databases...",
            lambda: self.intelligence.scan_gpd_directory(
                path, profile_id=profile_id
            ),
            "gpd-scan-complete",
        )

    def compare_profiles(self) -> None:
        left = self.profile_choices.get(self.compare_left_var.get(), "")
        right = self.profile_choices.get(self.compare_right_var.get(), "")
        if not left or not right:
            messagebox.showinfo(
                "Compare profiles",
                "Choose two indexed profiles first.",
                parent=self.root,
            )
            return
        try:
            result = self.intelligence.compare_profiles(left, right)
        except Exception as exc:
            messagebox.showerror("Comparison failed", str(exc), parent=self.root)
            return
        lines = [
            "PROFILE COMPARISON",
            "",
            f"Identical save titles: {len(result['save_titles_identical'])}",
            f"Different save titles: {len(result['save_titles_different'])}",
            f"Only in first profile: {', '.join(result['save_titles_only_left']) or 'None'}",
            f"Only in second profile: {', '.join(result['save_titles_only_right']) or 'None'}",
            "",
            f"Shared unlocked achievements: {result['achievements_shared']}",
            f"Unlocked only in first: {len(result['achievements_only_left'])}",
            f"Unlocked only in second: {len(result['achievements_only_right'])}",
            "",
            "This is a read-only comparison. No profile or save was changed.",
        ]
        self.compare_text.configure(state=tk.NORMAL)
        self.compare_text.delete("1.0", tk.END)
        self.compare_text.insert(tk.END, "\n".join(lines))
        self.compare_text.configure(state=tk.DISABLED)

    def choose_xenia_root(self) -> None:
        path = filedialog.askdirectory(
            parent=self.root,
            title="Choose Xenia folder or content directory",
        )
        if path:
            self.xenia_root_var.set(path)

    def choose_xenia_game(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Choose a game image or executable",
            filetypes=(("Xbox games", "*.xex *.iso"), ("All files", "*.*")),
        )
        if not path:
            path = filedialog.askdirectory(parent=self.root, title="Choose an extracted game")
        if path:
            self.xenia_game_var.set(path)

    def launch_xenia_game(self) -> None:
        installation = find_xenia_installation(self.xenia_root_var.get())
        if installation is None:
            messagebox.showerror(
                "Xenia", "No Xenia or Xenia Canary executable was found in that folder.",
                parent=self.root,
            )
            return
        try:
            result = launch_xenia(
                installation, self.xenia_game_var.get(),
                fullscreen=self.xenia_fullscreen_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("Xenia launch failed", str(exc), parent=self.root)
            return
        self.status_var.set(
            f"Launched {result['variant']} for {Path(str(result['game'])).name}."
        )

    def preview_xenia_migration(self) -> None:
        profile_id = self._selected_profile_id()
        if not profile_id:
            messagebox.showinfo(
                "Xenia migration", "Select a source profile first.", parent=self.root
            )
            return
        target_id = self.xenia_target_var.get().strip() or profile_id
        try:
            self.migration_plan = self.intelligence.preview_xenia_migration(
                profile_id,
                self.xenia_root_var.get(),
                target_profile_id=target_id,
            )
        except Exception as exc:
            messagebox.showerror("Migration preview failed", str(exc), parent=self.root)
            return
        self.migration_tree.delete(*self.migration_tree.get_children())
        for index, item in enumerate(self.migration_plan.items):
            self.migration_tree.insert(
                "",
                tk.END,
                iid=f"migration-{index}",
                values=(
                    item.title_id,
                    item.relative_path.name,
                    item.action.title(),
                    item.reason,
                ),
            )
        self.xenia_execute_button.configure(
            state=tk.NORMAL if self.migration_plan.copy_count else tk.DISABLED
        )
        self.status_var.set(
            f"Migration preview: {self.migration_plan.copy_count} copies, "
            f"{self.migration_plan.conflict_count} conflicts."
        )

    def execute_xenia_migration(self) -> None:
        plan = self.migration_plan
        if plan is None:
            return
        if not messagebox.askyesno(
            "Migrate saves to Xenia",
            "Create a verified snapshot, then copy every non-conflicting save "
            "shown in the preview?",
            parent=self.root,
        ):
            return
        self._run(
            "Creating a snapshot and migrating saves to Xenia...",
            lambda: self.intelligence.execute_xenia_migration(plan),
            "xenia-complete",
        )

    def refresh(self) -> None:
        self._refresh_profiles()
        self._refresh_snapshots()
        self._refresh_gpd_files()
        self._refresh_history()

    def _refresh_profiles(self) -> None:
        selected = self._selected_profile_id()
        self.profiles.clear()
        self.profile_tree.delete(*self.profile_tree.get_children())
        for row in self.manager.list_profiles():
            item_id = f"profile-{row['id']}"
            self.profiles[item_id] = row
            profile_id = str(row["profile_id"])
            gamertag = str(row.get("gamertag") or "")
            if self.reveal_var.get():
                label = f"{gamertag or 'Profile'} ({profile_id})"
            else:
                label = gamertag or f"Profile {mask_identifier(profile_id)}"
                if gamertag:
                    label = f"{mask_identifier(gamertag)} ({mask_identifier(profile_id)})"
            self.profile_tree.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    label,
                    int(row.get("save_count") or 0),
                    _size(int(row.get("total_size") or 0)),
                    row.get("package_status") or "unknown",
                ),
            )
            if selected and profile_id == selected:
                self.profile_tree.selection_set(item_id)
        if not self.profile_tree.selection() and self.profile_tree.get_children():
            first = self.profile_tree.get_children()[0]
            self.profile_tree.selection_set(first)
            self.profile_tree.focus(first)
        self._refresh_profile_choices()
        self._refresh_saves()

    def _refresh_profile_choices(self) -> None:
        current_left = self.compare_left_var.get()
        current_right = self.compare_right_var.get()
        self.profile_choices.clear()
        for row in self.profiles.values():
            profile_id = str(row["profile_id"])
            name = str(row.get("gamertag") or "Profile")
            label = f"{name} ({mask_identifier(profile_id)})"
            self.profile_choices[label] = profile_id
        choices = list(self.profile_choices)
        self.compare_left.configure(values=choices)
        self.compare_right.configure(values=choices)
        if current_left in self.profile_choices:
            self.compare_left_var.set(current_left)
        elif choices:
            self.compare_left_var.set(choices[0])
        if current_right in self.profile_choices:
            self.compare_right_var.set(current_right)
        elif len(choices) > 1:
            self.compare_right_var.set(choices[1])

    def _refresh_gpd_files(self) -> None:
        selected = self.gpd_tree.selection() if hasattr(self, "gpd_tree") else ()
        selected_id = selected[0] if selected else ""
        self.gpd_files.clear()
        self.gpd_tree.delete(*self.gpd_tree.get_children())
        for row in self.intelligence.list_gpd_files():
            item_id = f"gpd-{row['id']}"
            self.gpd_files[item_id] = row
            self.gpd_tree.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    row.get("titleid") or "Unknown",
                    f"{row['unlocked_count']} / {row['achievement_count']}",
                    f"{row['gamerscore_earned']} / {row['gamerscore_possible']}",
                    row["status"],
                    row["source_path"],
                ),
            )
        if selected_id in self.gpd_files:
            self.gpd_tree.selection_set(selected_id)
        elif self.gpd_tree.get_children():
            self.gpd_tree.selection_set(self.gpd_tree.get_children()[0])
        self._refresh_achievements()
        self._refresh_history()

    def _refresh_history(self) -> None:
        if not hasattr(self, "history_tree"):
            return
        self.history_tree.delete(*self.history_tree.get_children())
        rows = self.intelligence.list_title_history(self._selected_profile_id())
        for row in rows:
            self.history_tree.insert(
                "", tk.END,
                values=(
                    row.get("title") or "Unknown game", row["titleid"],
                    f"{row['achievements_earned']} / {row['achievements_possible']}",
                    f"{row['gamerscore_earned']} / {row['gamerscore_possible']}",
                    row.get("last_played_at") or "Unknown",
                ),
            )
        self.gpd_image_tree.delete(*self.gpd_image_tree.get_children())
        self.gpd_images.clear()
        image_count = 0
        for gpd in self.gpd_files.values():
            for image in self.intelligence.list_images(int(gpd["id"])):
                image_count += 1
                item_id = f"gpd-image-{gpd['id']}-{image['entry_id']}"
                image["source_path"] = gpd["source_path"]
                self.gpd_images[item_id] = image
                self.gpd_image_tree.insert(
                    "", tk.END, iid=item_id,
                    values=(image["image_format"].upper(), _size(image["size"]),
                            gpd["source_path"]),
                )
        self.history_summary_var.set(
            f"{len(rows)} played titles and {image_count} validated embedded images. "
            "Source GPD files remain unchanged."
        )

    def _refresh_achievements(self) -> None:
        if not hasattr(self, "achievement_tree"):
            return
        self.achievement_tree.delete(*self.achievement_tree.get_children())
        selection = self.gpd_tree.selection()
        if not selection:
            return
        row = self.gpd_files.get(selection[0])
        if not row:
            return
        for achievement in self.intelligence.list_achievements(
            int(row["id"]),
            search=self.achievement_search_var.get(),
        ):
            self.achievement_tree.insert(
                "",
                tk.END,
                values=(
                    achievement["achievement_id"],
                    achievement.get("title") or "Unnamed achievement",
                    achievement["gamerscore"],
                    str(achievement["unlock_state"]).replace("-", " ").title(),
                    str(achievement.get("unlocked_at") or "").replace("T", " ")[:19],
                ),
            )

    def _refresh_saves(self) -> None:
        profile_id = self._selected_profile_id()
        self.saves.clear()
        self.save_tree.delete(*self.save_tree.get_children())
        if not profile_id:
            return
        for row in self.manager.list_saves(profile_id, self.search_var.get()):
            item_id = f"save-{row['id']}"
            self.saves[item_id] = row
            modified = str(row.get("modified_at") or "").replace("T", " ")[:19]
            self.save_tree.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    row["name"],
                    row["titleid"],
                    _size(int(row["size"])),
                    row["status"],
                    modified,
                ),
            )

    def _refresh_snapshots(self) -> None:
        self.snapshots.clear()
        self.snapshot_tree.delete(*self.snapshot_tree.get_children())
        for row in self.manager.list_snapshots():
            item_id = f"snapshot-{row['id']}"
            self.snapshots[item_id] = row
            profile_id = str(row.get("profile_id") or "")
            profile_display = (
                profile_id if self.reveal_var.get() else mask_identifier(profile_id)
            )
            self.snapshot_tree.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    row["id"],
                    row.get("label") or "Profile snapshot",
                    profile_display,
                    str(row["created_at"]).replace("T", " ")[:19],
                    row["file_count"],
                    _size(int(row["total_size"])),
                    row["status"],
                ),
            )

    def _profile_selected(self, _event: tk.Event[Any]) -> None:
        self._refresh_saves()
        profile = self._selected_profile()
        if profile:
            source = (
                str(profile.get("source_path", ""))
                if self.reveal_var.get()
                else "Source path hidden"
            )
            self.detail_var.set(
                f"Profile {mask_identifier(str(profile['profile_id']))} | "
                f"{profile.get('save_count', 0)} saves | "
                f"{profile.get('package_status', 'unknown')} | "
                f"{source}"
            )

    def _save_selected(self, _event: tk.Event[Any]) -> None:
        selection = self.save_tree.selection()
        if not selection:
            return
        save = self.saves.get(selection[0])
        if save:
            self.detail_var.set(
                f"{save['name']} | TitleID {save['titleid']} | "
                f"Profile {mask_identifier(str(save['profile_id']))} | "
                f"SHA-256 {str(save.get('sha256') or '')[:16]}... | "
                f"{save['status']}"
            )

    def snapshot_profile(self) -> None:
        profile_id = self._selected_profile_id()
        if not profile_id:
            messagebox.showinfo(
                "Profile backup", "Select a profile first.", parent=self.root
            )
            return
        label = simpledialog.askstring(
            "Profile backup",
            "Optional snapshot label:",
            parent=self.root,
        )
        if label is None:
            return
        self._run(
            "Creating a verified profile snapshot...",
            lambda: self.manager.create_snapshot(profile_id, label=label),
            "snapshot-complete",
        )

    def snapshot_saves(self) -> None:
        profile_id = self._selected_profile_id()
        selected = [
            int(item.split("-", 1)[1])
            for item in self.save_tree.selection()
            if item in self.saves
        ]
        if not profile_id or not selected:
            messagebox.showinfo(
                "Save backup",
                "Select one or more saves first.",
                parent=self.root,
            )
            return
        label = simpledialog.askstring(
            "Save backup",
            "Optional snapshot label:",
            parent=self.root,
        )
        if label is None:
            return
        self._run(
            "Creating a verified save snapshot...",
            lambda: self.manager.create_snapshot(
                profile_id,
                save_ids=selected,
                label=label,
            ),
            "snapshot-complete",
        )

    def restore_snapshot(self) -> None:
        snapshot = self._selected_snapshot()
        if not snapshot:
            messagebox.showinfo(
                "Restore snapshot", "Select a snapshot first.", parent=self.root
            )
            return
        destination = filedialog.askdirectory(
            parent=self.root,
            title="Choose restore destination",
        )
        if not destination:
            return
        if not messagebox.askyesno(
            "Restore snapshot",
            "Restore into the selected folder?\n\n"
            "Different existing files will be preserved and the restored copy "
            "will be written alongside them.",
            parent=self.root,
        ):
            return
        snapshot_id = int(snapshot["id"])
        self._run(
            "Verifying and restoring snapshot...",
            lambda: self.manager.restore_snapshot(snapshot_id, destination),
            "restore-complete",
        )

    def export_manifest(self) -> None:
        snapshot = self._selected_snapshot()
        if not snapshot:
            messagebox.showinfo(
                "Export manifest", "Select a snapshot first.", parent=self.root
            )
            return
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export snapshot manifest",
            defaultextension=".json",
            filetypes=(("JSON manifest", "*.json"),),
        )
        if not destination:
            return
        try:
            result = self.manager.export_manifest(int(snapshot["id"]), destination)
        except Exception as exc:
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            return
        self.status_var.set(f"Manifest exported to {result}")

    def open_selected_source(self) -> None:
        selection = self.save_tree.selection()
        if selection and selection[0] in self.saves:
            open_path(Path(self.saves[selection[0]]["source_path"]).parent)
            return
        profile = self._selected_profile()
        if profile:
            open_path(profile["source_path"])

    def open_snapshot(self) -> None:
        snapshot = self._selected_snapshot()
        if snapshot:
            open_path(snapshot["snapshot_path"])

    def _run(
        self,
        status: str,
        operation: Callable[[], Any],
        event_name: str,
    ) -> None:
        if self.running:
            messagebox.showinfo(
                "Profiles & Saves",
                "Another profile operation is still running.",
                parent=self.root,
            )
            return
        self.running = True
        self.status_var.set(status)

        def worker() -> None:
            try:
                self.events.put((event_name, operation()))
            except Exception as exc:
                self.events.put(("failed", str(exc)))

        threading.Thread(target=worker, name="profile-save-operation", daemon=True).start()
        self.root.after(100, self._poll)

    def _poll(self) -> None:
        while True:
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            self.running = False
            if event == "failed":
                self.status_var.set("Profile operation failed")
                messagebox.showerror(
                    "Profiles & Saves", str(value), parent=self.root
                )
            elif event == "scan-complete":
                self.status_var.set(
                    f"Found {len(value.profiles)} profiles and "
                    f"{len(value.saves)} saves; {len(value.warnings)} warnings."
                )
                self.refresh()
            elif event == "snapshot-complete":
                self.status_var.set(f"Verified snapshot {value} created.")
                self.refresh()
            elif event == "restore-complete":
                self.status_var.set(
                    f"Restored {value.restored}; skipped {value.skipped}; "
                    f"preserved {value.conflicts} conflicts."
                )
                messagebox.showinfo(
                    "Restore complete",
                    f"Restored: {value.restored}\n"
                    f"Already present or skipped: {value.skipped}\n"
                    f"Conflicts preserved: {value.conflicts}",
                    parent=self.root,
                )
            elif event == "gpd-complete":
                self.status_var.set(f"GPD inventory record {value} imported.")
                self._refresh_gpd_files()
            elif event == "gpd-scan-complete":
                self.status_var.set(
                    f"Imported {value['imported']} GPD databases; "
                    f"{len(value['errors'])} could not be read."
                )
                self._refresh_gpd_files()
            elif event == "xenia-complete":
                self.status_var.set(
                    f"Xenia migration copied {value['copied']}; "
                    f"skipped {value['skipped']}; conflicts {value['conflicts']}."
                )
                self.migration_plan = None
                self.xenia_execute_button.configure(state=tk.DISABLED)
                self._refresh_snapshots()
                messagebox.showinfo(
                    "Xenia migration complete",
                    f"Snapshot: {value['snapshot_id']}\n"
                    f"Copied: {value['copied']}\n"
                    f"Skipped: {value['skipped']}\n"
                    f"Conflicts: {value['conflicts']}",
                    parent=self.root,
                )
        if self.running:
            self.root.after(100, self._poll)

    def _selected_profile(self) -> dict[str, Any] | None:
        selection = self.profile_tree.selection()
        return self.profiles.get(selection[0]) if selection else None

    def _selected_profile_id(self) -> str:
        profile = self._selected_profile()
        return str(profile["profile_id"]) if profile else ""

    def _selected_snapshot(self) -> dict[str, Any] | None:
        selection = self.snapshot_tree.selection()
        return self.snapshots.get(selection[0]) if selection else None

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_source(self) -> None:
        config = self._read_config()
        profiles = config.setdefault("profiles", {})
        if not isinstance(profiles, dict):
            profiles = {}
            config["profiles"] = profiles
        profiles["source_root"] = self.source_var.get()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

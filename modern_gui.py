"""
Library-first UnityScraper desktop interface.

This is intentionally a thin UI layer over the existing scraper and database.
The original GUI remains available as an advanced tools window.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk
from typing import Any

from app_paths import (
    BASE_DIR,
    CONFIG_PATH,
    DATABASE_PATH,
    DOWNLOADS_DIR,
    EXPORTS_DIR,
    GUI_LOG_PATH,
    TITLEIDS_PATH,
    describe_storage,
    ensure_app_dirs,
    ensure_user_titleids_file,
    resource_path,
)
from database import DatabaseManager
from diagnostics import create_diagnostics_bundle
from library_service import GameSummary, LibraryService
from setup_wizard import run_first_run_wizard


APP_VERSION = "0.8.0-beta"


def _open_path(path: Path) -> None:
    """Open a file or folder using the current operating system."""
    path = path.resolve()

    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])



class ResponsiveBackgroundBanner(ttk.Frame):
    """Responsive, center-cropped image banner for application pages."""

    def __init__(
        self,
        parent: tk.Misc,
        image_path: Path,
        title: str,
        subtitle: str,
        height: int = 280,
    ) -> None:
        super().__init__(parent)
        self.image_path = image_path
        self.title = title
        self.subtitle = subtitle
        self.banner_height = height
        self._source_image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._resize_job: str | None = None

        self.canvas = tk.Canvas(
            self,
            height=self.banner_height,
            highlightthickness=0,
            borderwidth=0,
            background="#0b0f0d",
        )
        self.canvas.pack(fill=tk.X, expand=True)

        if self.image_path.exists():
            try:
                self._source_image = Image.open(self.image_path).convert("RGB")
            except OSError:
                self._source_image = None

        self.bind("<Configure>", self._queue_redraw)
        self.canvas.bind("<Configure>", self._queue_redraw)
        self.after_idle(self._redraw)

    def _queue_redraw(self, _event: tk.Event[Any] | None = None) -> None:
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(60, self._redraw)

    def _redraw(self) -> None:
        self._resize_job = None
        width = max(self.canvas.winfo_width(), 640)
        height = self.banner_height
        self.canvas.delete("all")

        if self._source_image is not None:
            image = self._cover_resize(self._source_image, width, height)
            overlay = Image.new("RGB", image.size, "#050807")
            image = Image.blend(image, overlay, 0.05)
            self._photo = ImageTk.PhotoImage(image)
            self.canvas.create_image(0, 0, image=self._photo, anchor=tk.NW)
        else:
            self.canvas.create_rectangle(
                0, 0, width, height, fill="#0b0f0d", outline=""
            )
            self.canvas.create_text(
                width // 2,
                height // 2,
                text=f"Background not loaded: {self.image_path}",
                anchor=tk.CENTER,
                fill="#d6e6d3",
                font=("Segoe UI", 10),
            )

        self.canvas.create_rectangle(
            0, height - 5, width, height, fill="#5bd600", outline=""
        )
        self.canvas.create_text(
            28,
            54,
            text=self.title,
            anchor=tk.W,
            fill="#ffffff",
            font=("Segoe UI", 23, "bold"),
        )
        self.canvas.create_text(
            30,
            94,
            text=self.subtitle,
            anchor=tk.W,
            fill="#d6e6d3",
            width=max(width - 60, 300),
            font=("Segoe UI", 11),
        )

    @staticmethod
    def _cover_resize(image: Image.Image, width: int, height: int) -> Image.Image:
        """Fit the complete artwork inside the banner without destructive cropping."""
        fitted = ImageOps.contain(
            image,
            (width, height),
            method=Image.Resampling.LANCZOS,
        )
        background = Image.new("RGB", (width, height), "#080c0a")
        left = (width - fitted.width) // 2
        top = (height - fitted.height) // 2
        background.paste(fitted, (left, top))
        return background


class UnityScraperDesktop:
    """Main multi-page application window."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.library = LibraryService()
        self.database = DatabaseManager()
        self.current_game: str | None = None

        ensure_app_dirs()
        ensure_user_titleids_file()

        self.root.title(f"UnityScraper {APP_VERSION}")
        self.root.geometry("1220x780")
        self.root.minsize(980, 640)
        self._set_icon()
        self._configure_style()
        self._build_shell()

        if run_first_run_wizard(self.root):
            self.refresh_library()
        else:
            self.root.after(0, self.root.destroy)

    def _set_icon(self) -> None:
        icon = resource_path("assets", "UnityScraper.png")
        if not icon.exists():
            return
        try:
            self._icon_image = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon_image)
        except tk.TclError:
            pass

    def _configure_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            style.theme_use("clam")

        style.configure("Nav.TButton", anchor=tk.W, padding=(14, 11))
        style.configure("Header.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Subheader.TLabel", font=("Segoe UI", 11))
        style.configure("Metric.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("CardTitle.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("StatusDownloaded.TLabel", foreground="#237a3b")
        style.configure("StatusFailed.TLabel", foreground="#a51d2d")
        style.configure("StatusPending.TLabel", foreground="#856404")

    def _build_shell(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        nav = ttk.Frame(self.root, padding=(10, 14))
        nav.grid(row=0, column=0, sticky="ns")

        ttk.Label(nav, text="UnityScraper", font=("Segoe UI", 15, "bold")).pack(
            anchor=tk.W, padx=8, pady=(0, 16)
        )

        pages = (
            ("Library", self.show_library),
            ("Add Games", self.show_add_games),
            ("Downloads", self.show_downloads),
            ("Archive Health", self.show_health),
            ("Settings", self.show_settings),
            ("Help & About", self.show_about),
        )
        for label, callback in pages:
            ttk.Button(
                nav,
                text=label,
                command=callback,
                style="Nav.TButton",
                width=20,
            ).pack(fill=tk.X, pady=2)

        self.content = ttk.Frame(self.root, padding=20)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)

        self.show_library()

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _page_header(self, title: str, subtitle: str) -> None:
        background = resource_path(
            "assets",
            "backgrounds",
            "unityscraper_xbox_background.png",
        )
        header = ResponsiveBackgroundBanner(
            self.content,
            image_path=background,
            title=title,
            subtitle=subtitle,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 16))

    def show_library(self) -> None:
        self._clear_content()
        self._page_header(
            "Game Library",
            "Browse known games, cover art, MediaIDs, and available title updates.",
        )

        body = ttk.Frame(self.content)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=2)
        body.columnconfigure(1, weight=3)
        body.rowconfigure(2, weight=1)

        counts = self.library.get_dashboard_counts()
        metrics = ttk.Frame(body)
        metrics.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))

        metric_data = (
            ("Games", counts["games"]),
            ("Updates", counts["updates_available"]),
            ("Downloaded", counts["updates_downloaded"]),
            ("Failed", counts["failed"]),
        )
        for index, (label, value) in enumerate(metric_data):
            card = ttk.LabelFrame(metrics, text=label, padding=10)
            card.grid(row=0, column=index, sticky="ew", padx=(0, 8))
            metrics.columnconfigure(index, weight=1)
            ttk.Label(card, text=str(value), style="Metric.TLabel").pack(anchor=tk.W)

        search_row = ttk.Frame(body)
        search_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        search_row.columnconfigure(0, weight=1)

        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        search_entry.grid(row=0, column=0, sticky="ew")
        search_entry.bind("<Return>", lambda _event: self.refresh_library())
        ttk.Button(
            search_row,
            text="Search",
            command=self.refresh_library,
        ).grid(row=0, column=1, padx=(8, 0))
        ttk.Button(
            search_row,
            text="Refresh",
            command=self.refresh_library,
        ).grid(row=0, column=2, padx=(8, 0))

        list_frame = ttk.LabelFrame(body, text="Games", padding=8)
        list_frame.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.game_tree = ttk.Treeview(
            list_frame,
            columns=("titleid", "updates", "status"),
            show="tree headings",
            selectmode="browse",
        )
        self.game_tree.heading("#0", text="Game")
        self.game_tree.heading("titleid", text="TitleID")
        self.game_tree.heading("updates", text="Updates")
        self.game_tree.heading("status", text="Status")
        self.game_tree.column("#0", width=240)
        self.game_tree.column("titleid", width=90, anchor=tk.CENTER)
        self.game_tree.column("updates", width=75, anchor=tk.CENTER)
        self.game_tree.column("status", width=90, anchor=tk.CENTER)
        self.game_tree.grid(row=0, column=0, sticky="nsew")
        self.game_tree.bind("<<TreeviewSelect>>", self._game_selected)

        scrollbar = ttk.Scrollbar(
            list_frame, orient=tk.VERTICAL, command=self.game_tree.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.game_tree.configure(yscrollcommand=scrollbar.set)

        details = ttk.LabelFrame(body, text="Game Details", padding=12)
        details.grid(row=2, column=1, sticky="nsew")
        details.columnconfigure(0, weight=1)
        details.rowconfigure(1, weight=1)

        self.detail_title = ttk.Label(
            details, text="Select a game", style="CardTitle.TLabel"
        )
        self.detail_title.grid(row=0, column=0, sticky=tk.W, pady=(0, 8))

        self.detail_notebook = ttk.Notebook(details)
        self.detail_notebook.grid(row=1, column=0, sticky="nsew")

        self.updates_tree = self._detail_tree(
            self.detail_notebook,
            "Title Updates",
            ("media_id", "version", "status", "size"),
            ("MediaID", "Version", "Status", "Size"),
        )
        self.covers_tree = self._detail_tree(
            self.detail_notebook,
            "Covers",
            ("type", "resolution", "status", "size"),
            ("Type", "Resolution", "Status", "Size"),
        )

        detail_buttons = ttk.Frame(details)
        detail_buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(
            detail_buttons,
            text="Open Download Folder",
            command=lambda: _open_path(DOWNLOADS_DIR),
        ).pack(side=tk.LEFT)
        ttk.Button(
            detail_buttons,
            text="Open Advanced Tools",
            command=self._open_legacy_gui,
        ).pack(side=tk.RIGHT)

        self.refresh_library()

    def _detail_tree(
        self,
        notebook: ttk.Notebook,
        tab_name: str,
        columns: tuple[str, ...],
        headings: tuple[str, ...],
    ) -> ttk.Treeview:
        frame = ttk.Frame(notebook, padding=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        notebook.add(frame, text=tab_name)

        tree = ttk.Treeview(frame, columns=columns, show="headings")
        for column, heading in zip(columns, headings):
            tree.heading(column, text=heading)
            tree.column(column, width=110, anchor=tk.CENTER)
        tree.grid(row=0, column=0, sticky="nsew")
        return tree

    def refresh_library(self) -> None:
        if not hasattr(self, "game_tree"):
            return

        selected = self.current_game
        self.game_tree.delete(*self.game_tree.get_children())

        games = self.library.list_games(self.search_var.get())
        for game in games:
            status = self._summary_status(game)
            item = self.game_tree.insert(
                "",
                tk.END,
                iid=game.titleid,
                text=game.name,
                values=(
                    game.titleid,
                    f"{game.updates_downloaded}/{game.updates_total}",
                    status,
                ),
            )
            if game.titleid == selected:
                self.game_tree.selection_set(item)
                self.game_tree.focus(item)

        if not games:
            self.detail_title.configure(
                text="No games found. Use Add Games to import TitleIDs."
            )
        elif selected not in {game.titleid for game in games}:
            first = games[0].titleid
            self.game_tree.selection_set(first)
            self.game_tree.focus(first)
            self._load_game(first)

    @staticmethod
    def _summary_status(game: GameSummary) -> str:
        if game.updates_failed:
            return "Needs attention"
        if game.updates_total and game.updates_downloaded == game.updates_total:
            return "Complete"
        if game.updates_total:
            return "Updates available"
        return "Metadata only"

    def _game_selected(self, _event: tk.Event[Any]) -> None:
        selection = self.game_tree.selection()
        if selection:
            self._load_game(selection[0])

    def _load_game(self, titleid: str) -> None:
        self.current_game = titleid
        details = self.library.get_game_details(titleid)
        if not details:
            return

        title = details["title"]
        name = title.get("name") or titleid
        publisher = title.get("publisher") or "Unknown publisher"
        self.detail_title.configure(text=f"{name}  •  {titleid}  •  {publisher}")

        self.updates_tree.delete(*self.updates_tree.get_children())
        for update in details["updates"]:
            self.updates_tree.insert(
                "",
                tk.END,
                values=(
                    update.get("media_id") or "Unknown",
                    update.get("version") or "Unknown",
                    update.get("status") or "pending",
                    self._format_size(update.get("file_size")),
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
                    self._format_size(cover.get("file_size")),
                ),
            )

    @staticmethod
    def _format_size(size: Any) -> str:
        if not size:
            return "—"
        value = float(size)
        for suffix in ("B", "KB", "MB", "GB"):
            if value < 1024 or suffix == "GB":
                return f"{value:.1f} {suffix}"
            value /= 1024
        return "—"

    def show_add_games(self) -> None:
        self._clear_content()
        self._page_header(
            "Add Games",
            "Import TitleIDs without editing JSON.txt by hand.",
        )

        panel = ttk.LabelFrame(self.content, text="TitleID Import", padding=18)
        panel.grid(row=1, column=0, sticky="new")
        panel.columnconfigure(0, weight=1)

        ttk.Label(
            panel,
            text="Enter one or more 8-character hexadecimal TitleIDs:",
        ).grid(row=0, column=0, sticky=tk.W)

        self.add_titleids_text = tk.Text(panel, height=8, wrap=tk.WORD)
        self.add_titleids_text.grid(row=1, column=0, sticky="ew", pady=8)

        actions = ttk.Frame(panel)
        actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(
            actions, text="Import Text File…", command=self._import_titleid_file
        ).pack(side=tk.LEFT)
        ttk.Button(
            actions, text="Save TitleIDs", command=self._save_titleids
        ).pack(side=tk.RIGHT)

        ttk.Label(
            panel,
            text=(
                "After saving, open Advanced Tools and choose “Collect Metadata” "
                "to scan XboxUnity for covers and title updates."
            ),
            wraplength=760,
        ).grid(row=3, column=0, sticky=tk.W, pady=(18, 0))

    def _import_titleid_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Import TitleIDs",
            filetypes=(
                ("Text and CSV", "*.txt *.csv"),
                ("All files", "*.*"),
            ),
        )
        if not selected:
            return

        try:
            content = Path(selected).read_text(encoding="utf-8-sig")
        except OSError as exc:
            messagebox.showerror("Import failed", str(exc), parent=self.root)
            return

        self.add_titleids_text.insert(tk.END, f"\n{content}")

    def _save_titleids(self) -> None:
        raw = self.add_titleids_text.get("1.0", tk.END)
        values = [
            value.strip().upper()
            for value in raw.replace("\n", ",").replace(";", ",").split(",")
            if value.strip()
        ]

        valid: list[str] = []
        invalid: list[str] = []
        for value in values:
            if len(value) == 8 and all(character in "0123456789ABCDEF" for character in value):
                valid.append(value)
            else:
                invalid.append(value)

        existing = []
        if TITLEIDS_PATH.exists():
            existing = [
                value.strip().upper()
                for value in TITLEIDS_PATH.read_text(encoding="utf-8").replace(
                    "\n", ","
                ).split(",")
                if value.strip()
            ]

        merged = list(dict.fromkeys(existing + valid))
        TITLEIDS_PATH.write_text(",".join(merged), encoding="utf-8")

        message = f"Saved {len(valid)} valid TitleID(s)."
        if invalid:
            message += "\n\nSkipped invalid entries:\n" + "\n".join(invalid[:20])

        messagebox.showinfo("TitleIDs saved", message, parent=self.root)

    def show_downloads(self) -> None:
        self._clear_content()
        self._page_header(
            "Downloads",
            "Use the existing download engine while the new queue view is developed.",
        )

        panel = ttk.LabelFrame(self.content, text="Download Tools", padding=18)
        panel.grid(row=1, column=0, sticky="new")

        ttk.Label(
            panel,
            text=(
                "The current scraper engine, retry controls, queue, rate limiting, "
                "and download logs remain available in Advanced Tools."
            ),
            wraplength=760,
        ).pack(anchor=tk.W)

        ttk.Button(
            panel,
            text="Open Advanced Download Tools",
            command=self._open_legacy_gui,
        ).pack(anchor=tk.W, pady=(16, 6))

        ttk.Button(
            panel,
            text="Open Download Folder",
            command=lambda: _open_path(DOWNLOADS_DIR),
        ).pack(anchor=tk.W, pady=6)

        ttk.Button(
            panel,
            text="Open GUI Log",
            command=self._open_log,
        ).pack(anchor=tk.W, pady=6)

    def show_health(self) -> None:
        self._clear_content()
        self._page_header(
            "Archive Health",
            "Find missing, zero-byte, and duplicate files in the local archive.",
        )

        panel = ttk.Frame(self.content)
        panel.grid(row=1, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        ttk.Button(
            panel,
            text="Run Archive Scan",
            command=self._run_health_scan,
        ).grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        self.health_text = tk.Text(panel, wrap=tk.WORD)
        self.health_text.grid(row=1, column=0, sticky="nsew")
        self.health_text.insert(
            tk.END,
            "Select “Run Archive Scan” to verify downloaded database records.\n",
        )
        self.health_text.configure(state=tk.DISABLED)

    def _run_health_scan(self) -> None:
        self.root.config(cursor="watch")
        self.root.update_idletasks()
        try:
            report = self.library.scan_archive_health()
        except OSError as exc:
            messagebox.showerror("Scan failed", str(exc), parent=self.root)
            return
        finally:
            self.root.config(cursor="")

        output = [
            f"Records checked: {report['checked']}",
            f"Healthy files: {len(report['healthy'])}",
            f"Missing files: {len(report['missing'])}",
            f"Empty files: {len(report['empty'])}",
            f"Duplicate file groups: {len(report['duplicate_files'])}",
            f"Duplicate database groups: {len(report['database_duplicates'])}",
            "",
        ]

        for category in ("missing", "empty"):
            if report[category]:
                output.append(category.upper())
                for item in report[category]:
                    output.append(
                        f"• {item.get('titleid')} — {item.get('file_path') or item.get('reason')}"
                    )
                output.append("")

        self.health_text.configure(state=tk.NORMAL)
        self.health_text.delete("1.0", tk.END)
        self.health_text.insert(tk.END, "\n".join(output))
        self.health_text.configure(state=tk.DISABLED)

    def show_settings(self) -> None:
        self._clear_content()
        self._page_header(
            "Settings",
            "Safe defaults are shown first; network tuning remains optional.",
        )

        config = self._read_config()
        panel = ttk.LabelFrame(self.content, text="Application Settings", padding=18)
        panel.grid(row=1, column=0, sticky="new")
        panel.columnconfigure(1, weight=1)

        self.output_var = tk.StringVar(
            value=str(config.get("output_dir", DOWNLOADS_DIR))
        )
        self.workers_var = tk.IntVar(value=int(config.get("workers", 4)))
        self.rate_var = tk.DoubleVar(value=float(config.get("rate_limit", 0.35)))
        self.timeout_var = tk.IntVar(value=int(config.get("timeout", 30)))
        self.retries_var = tk.IntVar(value=int(config.get("max_retries", 3)))

        ttk.Label(panel, text="Archive folder").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(panel, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(panel, text="Browse…", command=self._browse_output).grid(
            row=0, column=2
        )

        ttk.Separator(panel).grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=16
        )
        ttk.Label(
            panel, text="Advanced networking", style="CardTitle.TLabel"
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W)

        fields = (
            ("Parallel workers", self.workers_var, 1, 16),
            ("Minimum request delay", self.rate_var, 0.1, 5.0),
            ("Timeout seconds", self.timeout_var, 5, 120),
            ("Maximum retries", self.retries_var, 0, 10),
        )
        for offset, (label, variable, minimum, maximum) in enumerate(fields, start=3):
            ttk.Label(panel, text=label).grid(
                row=offset, column=0, sticky=tk.W, pady=5
            )
            ttk.Spinbox(
                panel,
                textvariable=variable,
                from_=minimum,
                to=maximum,
                width=12,
            ).grid(row=offset, column=1, sticky=tk.W, padx=8)

        ttk.Button(
            panel,
            text="Save Settings",
            command=self._save_settings,
        ).grid(row=8, column=2, sticky=tk.E, pady=(16, 0))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.root,
            initialdir=self.output_var.get(),
        )
        if selected:
            self.output_var.set(selected)

    def _save_settings(self) -> None:
        output = Path(self.output_var.get()).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Invalid folder", str(exc), parent=self.root)
            return

        config = self._read_config()
        config.update(
            {
                "output_dir": str(output),
                "workers": self.workers_var.get(),
                "rate_limit": self.rate_var.get(),
                "timeout": self.timeout_var.get(),
                "max_retries": self.retries_var.get(),
            }
        )
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        messagebox.showinfo("Settings", "Settings saved.", parent=self.root)

    @staticmethod
    def _read_config() -> dict[str, Any]:
        if not CONFIG_PATH.exists():
            return {}
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def show_about(self) -> None:
        self._clear_content()
        self._page_header(
            "Help & About",
            "Diagnostics, local storage, and project information.",
        )

        panel = ttk.LabelFrame(self.content, text="UnityScraper", padding=18)
        panel.grid(row=1, column=0, sticky="new")

        ttk.Label(
            panel,
            text=f"Version {APP_VERSION}",
            style="CardTitle.TLabel",
        ).pack(anchor=tk.W)
        ttk.Label(
            panel,
            text=(
                "Xbox 360 title-update, cover-art, and preservation manager.\n\n"
                + describe_storage()
            ),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(8, 18))

        ttk.Button(
            panel,
            text="Export Diagnostics ZIP",
            command=self._export_diagnostics,
        ).pack(anchor=tk.W, pady=4)
        ttk.Button(
            panel,
            text="Open Application Data",
            command=lambda: _open_path(BASE_DIR),
        ).pack(anchor=tk.W, pady=4)
        ttk.Button(
            panel,
            text="Open GitHub Project",
            command=lambda: webbrowser.open(
                "https://github.com/TrapEmAll/UnityScraper"
            ),
        ).pack(anchor=tk.W, pady=4)

    def _export_diagnostics(self) -> None:
        try:
            bundle = create_diagnostics_bundle()
        except OSError as exc:
            messagebox.showerror("Diagnostics failed", str(exc), parent=self.root)
            return

        messagebox.showinfo(
            "Diagnostics created",
            f"Created:\n{bundle}",
            parent=self.root,
        )
        _open_path(bundle.parent)

    def _open_log(self) -> None:
        if GUI_LOG_PATH.exists():
            _open_path(GUI_LOG_PATH)
        else:
            messagebox.showinfo(
                "No log yet",
                "The GUI log has not been created yet.",
                parent=self.root,
            )

    def _open_legacy_gui(self) -> None:
        """Open the existing GUI as a separate advanced-tools window."""
        try:
            from GUI import UnityScraperGUI
        except ImportError as exc:
            messagebox.showerror(
                "Advanced tools unavailable",
                str(exc),
                parent=self.root,
            )
            return

        window = tk.Toplevel(self.root)
        UnityScraperGUI(window)


def main() -> None:
    root = tk.Tk()
    UnityScraperDesktop(root)
    root.mainloop()


if __name__ == "__main__":
    main()

"""Settings page: appearance, accessibility, library and download options, database backups."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any

from i18n import SUPPORTED_LANGUAGES
from platform_support import open_path
from ui_theme import ACCENTS, DEFAULT_ACCENT, DEFAULT_THEME, PALETTE, THEME_LABELS
from unityscraper.app.desktop.shell import format_size
from unityscraper.core.config import read_config, update_config
from unityscraper.core.db_backups import KEEP_RANGE, AutoBackupService, BackupInfo
from unityscraper.core.paths import DOWNLOADS_DIR

if TYPE_CHECKING:
    from modern_gui import UnityScraperDesktop

BACKUP_INTERVALS = {
    6: "Every 6 hours", 12: "Every 12 hours", 24: "Daily", 48: "Every 2 days", 168: "Weekly",
}
ACCESSIBILITY_OPTIONS = (
    ("large_text", "Large text", "Bigger fonts plus a quarter step of interface scale."),
    ("high_contrast", "High contrast", "Maximum-contrast colors regardless of the theme."),
    ("reduced_motion", "Reduced motion", "Avoid animated transitions."),
    ("keyboard_hints", "Keyboard hints", "Show keyboard shortcut hints."),
)
# (config key, label, minimum, maximum, increment, default)
NUMERIC_FIELDS = (
    ("workers", "Parallel workers", 1, 16, 1, 4),
    ("rate_limit", "Minimum request delay (seconds)", 0.1, 5.0, 0.05, 0.35),
    ("timeout", "Timeout (seconds)", 5, 120, 1, 30),
    ("max_retries", "Maximum retries", 0, 10, 1, 3),
)


class SettingsPage:
    """Scrollable settings cards; appearance, accessibility and backups apply immediately."""

    def __init__(self, app: UnityScraperDesktop) -> None:
        self.app = app
        self.backups = AutoBackupService()
        app._page_header(
            "Settings", "Appearance, accessibility, downloads, and database backups."
        )
        config = read_config()
        self.theme = str(config.get("theme", DEFAULT_THEME))
        self.accent = str(config.get("accent", DEFAULT_ACCENT))
        self.saved_scale = float(config.get("ui_scale", 1.0))

        # Checkbuttons and radiobuttons default to the page background; match the card surface.
        style = ttk.Style(app.root)
        for widget in ("TCheckbutton", "TRadiobutton"):
            style.configure(f"Card.{widget}", background=PALETTE.panel_alt)
            style.map(f"Card.{widget}", background=[("active", PALETTE.panel_alt)])

        body = ttk.Frame(app.content)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        column = self._scroll_area(body)

        self._build_appearance(column, config)
        self._build_accessibility(column)
        self._build_library(column, config)
        self._build_backups(column)

        footer = ttk.Frame(body)
        footer.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(
            footer,
            text="Save applies the scale, language, library, and download fields.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT)
        ttk.Button(
            footer, text="Save changes", style="Accent.TButton", command=self._save
        ).pack(side=tk.RIGHT)

        self._refresh_backups()

    # ------------------------------------------------------------ layout

    def _scroll_area(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, background=PALETTE.panel, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        column = ttk.Frame(canvas)
        window = canvas.create_window(0, 0, window=column, anchor=tk.NW)
        column.bind(
            "<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

        def scroll(event: tk.Event) -> None:
            up = getattr(event, "delta", 0) > 0 or getattr(event, "num", 0) == 4
            canvas.yview_scroll(-1 if up else 1, "units")

        def bind_wheel(_event: tk.Event) -> None:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.bind_all(sequence, scroll)

        def unbind_wheel(_event: tk.Event) -> None:
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                canvas.unbind_all(sequence)

        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)
        canvas.bind("<Destroy>", unbind_wheel)
        return column

    def _card(self, parent: ttk.Frame, title: str, subtitle: str = "") -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=16)
        card.pack(fill=tk.X, pady=(0, 16))
        card.columnconfigure(1, weight=1)
        ttk.Label(card, text=title, style="CardHeading.TLabel").grid(
            row=0, column=0, columnspan=3, sticky=tk.W
        )
        if subtitle:
            ttk.Label(card, text=subtitle, style="CardMuted.TLabel").grid(
                row=1, column=0, columnspan=3, sticky=tk.W, pady=(2, 0)
            )
        return card

    # -------------------------------------------------------- appearance

    def _build_appearance(self, parent: ttk.Frame, config: dict[str, Any]) -> None:
        card = self._card(parent, "Appearance", "Theme and accent changes apply immediately.")

        ttk.Label(card, text="Theme", style="Card.TLabel").grid(
            row=2, column=0, sticky=tk.W, pady=(12, 4)
        )
        themes = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        themes.grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=8, pady=(12, 4))
        self.theme_var = tk.StringVar(value=self.theme)
        for value, label in THEME_LABELS.items():
            ttk.Radiobutton(
                themes, text=label, value=value, variable=self.theme_var,
                style="Card.TRadiobutton",
                command=lambda: self._apply_theme(self.theme_var.get(), self.accent),
            ).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(card, text="Accent", style="Card.TLabel").grid(
            row=3, column=0, sticky=tk.W, pady=4
        )
        swatches = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        swatches.grid(row=3, column=1, columnspan=2, sticky=tk.W, padx=8, pady=4)
        for name, (dark_shade, light_shade) in ACCENTS.items():
            current = name == self.accent
            swatch = tk.Frame(
                swatches, width=26, height=26, cursor="hand2", takefocus=True,
                background=light_shade if self.theme == "light" else dark_shade,
                highlightthickness=3,
                highlightbackground=PALETTE.text if current else PALETTE.panel_alt,
                highlightcolor=PALETTE.border_hot,
            )
            swatch.pack(side=tk.LEFT, padx=(0, 8))
            for sequence in ("<Button-1>", "<Return>", "<space>"):
                swatch.bind(
                    sequence, lambda _event, accent=name: self._apply_theme(self.theme, accent)
                )
        if self.theme == "high_contrast":
            ttk.Label(
                card, text="High contrast always uses a yellow accent.", style="CardMuted.TLabel"
            ).grid(row=4, column=1, columnspan=2, sticky=tk.W, padx=8)

        self.scale_var = tk.DoubleVar(value=self.saved_scale)
        ttk.Label(card, text="Interface scale", style="Card.TLabel").grid(
            row=5, column=0, sticky=tk.W, pady=(12, 4)
        )
        ttk.Spinbox(
            card, textvariable=self.scale_var, from_=0.8, to=2.0, increment=0.05,
            format="%.2f", width=8,
        ).grid(row=5, column=1, sticky=tk.W, padx=8, pady=(12, 4))

        self.language_var = tk.StringVar(value=str(config.get("language", "en")))
        ttk.Label(card, text="Language", style="Card.TLabel").grid(
            row=6, column=0, sticky=tk.W, pady=4
        )
        language = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        language.grid(row=6, column=1, columnspan=2, sticky=tk.W, padx=8, pady=4)
        ttk.Combobox(
            language, textvariable=self.language_var, state="readonly",
            values=tuple(SUPPORTED_LANGUAGES), width=8,
        ).pack(side=tk.LEFT)
        ttk.Label(language, text="Applies after restart", style="CardMuted.TLabel").pack(
            side=tk.LEFT, padx=(10, 0)
        )

    def _apply_theme(self, theme: str, accent: str) -> None:
        if (theme, accent) != (self.theme, self.accent):
            self.app.set_theme(theme, accent)

    # ----------------------------------------------------- accessibility

    def _build_accessibility(self, parent: ttk.Frame) -> None:
        card = self._card(parent, "Accessibility", "Changes apply immediately.")
        preferences = self.app.accessibility_preferences
        for row, (key, label, hint) in enumerate(ACCESSIBILITY_OPTIONS, start=2):
            variable = tk.BooleanVar(value=bool(preferences.get(key)))
            ttk.Checkbutton(
                card, text=label, variable=variable, style="Card.TCheckbutton",
                command=lambda key=key, variable=variable: self._set_accessibility(
                    key, variable.get()
                ),
            ).grid(row=row, column=0, sticky=tk.W, pady=(10 if row == 2 else 2, 2))
            ttk.Label(card, text=hint, style="CardMuted.TLabel").grid(
                row=row, column=1, columnspan=2, sticky=tk.W, padx=8
            )

    def _set_accessibility(self, key: str, value: bool) -> None:
        self.app.accessibility.set(key, value)
        self.app.accessibility_preferences[key] = value
        if key == "large_text":
            self.app.apply_ui_scale(self.saved_scale)
        self.app.rebuild()

    # ------------------------------------------------- library/downloads

    def _build_library(self, parent: ttk.Frame, config: dict[str, Any]) -> None:
        card = self._card(parent, "Library & Downloads", "Saved with Save changes.")

        self.output_var = tk.StringVar(value=str(config.get("output_dir", DOWNLOADS_DIR)))
        ttk.Label(card, text="Archive folder", style="Card.TLabel").grid(
            row=2, column=0, sticky=tk.W, pady=(12, 4)
        )
        ttk.Entry(card, textvariable=self.output_var).grid(
            row=2, column=1, sticky="ew", padx=8, pady=(12, 4)
        )
        ttk.Button(card, text="Browse…", command=self._browse_output).grid(
            row=2, column=2, pady=(12, 4)
        )

        self.numeric_vars: dict[str, tk.Variable] = {}
        for row, (key, label, minimum, maximum, step, default) in enumerate(
            NUMERIC_FIELDS, start=3
        ):
            is_float = isinstance(step, float)
            variable: tk.Variable = (
                tk.DoubleVar(value=float(config.get(key, default))) if is_float
                else tk.IntVar(value=int(config.get(key, default)))
            )
            self.numeric_vars[key] = variable
            ttk.Label(card, text=label, style="Card.TLabel").grid(
                row=row, column=0, sticky=tk.W, pady=4
            )
            ttk.Spinbox(
                card, textvariable=variable, from_=minimum, to=maximum, increment=step,
                width=8, **({"format": "%.2f"} if is_float else {}),
            ).grid(row=row, column=1, sticky=tk.W, padx=8, pady=4)

        self.catalog_var = tk.BooleanVar(
            value=bool(config.get("sync_title_catalog_on_start", True))
        )
        ttk.Checkbutton(
            card, text="Refresh XboxUnity title catalog on start",
            variable=self.catalog_var, style="Card.TCheckbutton",
        ).grid(row=3 + len(NUMERIC_FIELDS), column=0, columnspan=3, sticky=tk.W, pady=(10, 0))

    def _browse_output(self) -> None:
        selected = filedialog.askdirectory(parent=self.app.root, initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)

    def _save(self) -> None:
        raw_output = self.output_var.get().strip()
        if not raw_output:
            self.app.notify("warning", "Invalid folder", "Choose an archive folder.")
            return
        output = Path(raw_output).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.app.notify("error", "Invalid folder", str(exc))
            return
        try:
            scale = max(0.8, min(2.0, float(self.scale_var.get())))
            numbers = {
                key: max(minimum, min(maximum, self.numeric_vars[key].get()))
                for key, _label, minimum, maximum, _step, _default in NUMERIC_FIELDS
            }
        except (tk.TclError, ValueError):
            self.app.notify("warning", "Invalid value", "Enter numbers in the numeric fields.")
            return

        previous_language = str(read_config().get("language", "en"))
        language = self.language_var.get()
        update_config(
            {
                "output_dir": str(output),
                **numbers,
                "ui_scale": scale,
                "language": language,
                "sync_title_catalog_on_start": self.catalog_var.get(),
            }
        )
        if scale != self.saved_scale:
            self.app.apply_ui_scale(scale)
            self.app.rebuild()
        self.app.notify(
            "success",
            "Settings saved",
            "Language changes apply after restart." if language != previous_language else "",
        )

    # ----------------------------------------------------------- backups

    def _build_backups(self, parent: ttk.Frame) -> None:
        card = self._card(
            parent,
            "Database Backups",
            f"Stored in {self.backups.backup_dir}. Manual backups are never deleted automatically.",
        )
        settings = self.backups.settings()
        interval = int(settings["interval_hours"])
        self.interval_labels = dict(BACKUP_INTERVALS)
        self.interval_labels.setdefault(interval, f"Every {interval} hours")

        self.backup_enabled_var = tk.BooleanVar(value=bool(settings["enabled"]))
        ttk.Checkbutton(
            card, text="Back up automatically", variable=self.backup_enabled_var,
            style="Card.TCheckbutton", command=self._save_backup_settings,
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(12, 4))

        ttk.Label(card, text="Frequency", style="Card.TLabel").grid(
            row=3, column=0, sticky=tk.W, pady=4
        )
        self.interval_var = tk.StringVar(value=self.interval_labels[interval])
        interval_box = ttk.Combobox(
            card, textvariable=self.interval_var, state="readonly", width=16,
            values=tuple(self.interval_labels.values()),
        )
        interval_box.grid(row=3, column=1, sticky=tk.W, padx=8, pady=4)
        interval_box.bind("<<ComboboxSelected>>", lambda _event: self._save_backup_settings())

        ttk.Label(card, text="Automatic backups to keep", style="Card.TLabel").grid(
            row=4, column=0, sticky=tk.W, pady=4
        )
        self.keep_var = tk.IntVar(value=int(settings["keep"]))
        keep_box = ttk.Spinbox(
            card, textvariable=self.keep_var, from_=KEEP_RANGE[0], to=KEEP_RANGE[1], width=8,
            command=self._save_backup_settings,
        )
        keep_box.grid(row=4, column=1, sticky=tk.W, padx=8, pady=4)
        for sequence in ("<FocusOut>", "<Return>"):
            keep_box.bind(sequence, lambda _event: self._save_backup_settings())

        actions = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        actions.grid(row=5, column=0, columnspan=3, sticky=tk.W, pady=(12, 8))
        ttk.Button(
            actions, text="Back up now", style="Accent.TButton", command=self._backup_now
        ).pack(side=tk.LEFT)
        ttk.Button(actions, text="Open backups folder", command=self._open_backup_folder).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        tree_frame = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        tree_frame.grid(row=6, column=0, columnspan=3, sticky="ew")
        tree_frame.columnconfigure(0, weight=1)
        self.backup_tree = ttk.Treeview(
            tree_frame, columns=("date", "type", "size"), show="headings", height=6,
            selectmode="browse",
        )
        for column, heading, width in (
            ("date", "Date", 220), ("type", "Type", 120), ("size", "Size", 100),
        ):
            self.backup_tree.heading(column, text=heading, anchor=tk.W)
            self.backup_tree.column(column, width=width, anchor=tk.W, stretch=column == "date")
        self.backup_tree.grid(row=0, column=0, sticky="ew")
        tree_scroll = ttk.Scrollbar(
            tree_frame, orient=tk.VERTICAL, command=self.backup_tree.yview
        )
        self.backup_tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.grid(row=0, column=1, sticky="ns")

        restore = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        restore.grid(row=7, column=0, columnspan=3, sticky=tk.W, pady=(8, 0))
        ttk.Button(restore, text="Restore selected…", command=self._restore_selected).pack(
            side=tk.LEFT
        )
        ttk.Button(restore, text="Restore from file…", command=self._restore_from_file).pack(
            side=tk.LEFT, padx=(8, 0)
        )

    def _save_backup_settings(self) -> None:
        hours = next(
            (value for value, label in self.interval_labels.items()
             if label == self.interval_var.get()),
            24,
        )
        try:
            keep = int(self.keep_var.get())
        except (tk.TclError, ValueError):
            self.app.notify("warning", "Invalid value", "Backups to keep must be a number.")
            return
        self.backups.configure(self.backup_enabled_var.get(), hours, keep)
        self.keep_var.set(self.backups.settings()["keep"])

    def _refresh_backups(self) -> None:
        self.app.run_background("Listing database backups", self.backups.list, self._show_backups)

    def _show_backups(self, backups: list[BackupInfo]) -> None:
        if not self.backup_tree.winfo_exists():
            return  # The page was rebuilt or left while listing.
        self.backup_tree.delete(*self.backup_tree.get_children())
        for backup in backups:
            self.backup_tree.insert(
                "", tk.END, iid=str(backup.path),
                values=(
                    backup.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "Automatic" if backup.automatic else "Manual",
                    format_size(backup.size),
                ),
            )

    def _backup_now(self) -> None:
        def done(backup: BackupInfo) -> None:
            self.app.notify("success", "Database backed up", backup.path.name, source="Settings")
            if self.backup_tree.winfo_exists():
                self._refresh_backups()

        self.app.run_background(
            "Backing up database", lambda: self.backups.create(automatic=False), done
        )

    def _open_backup_folder(self) -> None:
        try:
            self.backups.backup_dir.mkdir(parents=True, exist_ok=True)
            open_path(self.backups.backup_dir)
        except (OSError, RuntimeError) as exc:
            self.app.notify("error", "Unable to open backups folder", str(exc))

    def _restore_selected(self) -> None:
        selection = self.backup_tree.selection()
        if not selection:
            self.app.notify("info", "No backup selected", "Select a backup in the list first.")
            return
        self._restore(Path(selection[0]))

    def _restore_from_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.app.root,
            title="Choose UnityScraper database backup",
            initialdir=str(self.backups.backup_dir) if self.backups.backup_dir.is_dir() else None,
            filetypes=(("SQLite database", "*.db *.bak"), ("All files", "*.*")),
        )
        if selected:
            self._restore(Path(selected))

    def _restore(self, source: Path) -> None:
        if not messagebox.askyesno(
            "Restore database",
            f"Replace the current database with:\n{source}\n\n"
            "A safety backup of the current database is made first. "
            "UnityScraper closes when the restore finishes. Continue?",
            icon=messagebox.WARNING,
            parent=self.app.root,
        ):
            return

        def done(safety: Path) -> None:
            self.app.notify(
                "success", "Database restored", f"Previous database saved as {safety.name}",
                source="Settings", toast=False,
            )
            messagebox.showinfo(
                "Database restored",
                f"Restore completed. Previous database backup:\n{safety}\n\n"
                "UnityScraper will now close.",
                parent=self.app.root,
            )
            self.app.root.destroy()

        self.app.run_background("Restoring database", lambda: self.backups.restore(source), done)

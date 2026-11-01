"""
Library-first UnityScraper desktop interface.

This is intentionally a thin UI layer over the existing scraper and database.
The original GUI remains available as an advanced tools window.
"""

from __future__ import annotations

import queue
import re
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, TypeVar

from app_paths import (
    BASE_DIR,
    CONFIG_PATH,
    GUI_LOG_PATH,
    LANGUAGE_PACKS_DIR,
    TITLEIDS_PATH,
    describe_storage,
    portable_mode_enabled,
    ensure_app_dirs,
    ensure_user_titleids_file,
    resource_path,
)
from app_version import DISPLAY_VERSION
from backup_gui import BackupPage
from collection_gui import CollectionPage
from collection_intelligence import CollectionIntelligenceService
from community_gui import CommunityHubPage
from community_services import AccessibilityService
from backup_service import BackupService
from database import DatabaseManager
from diagnostics import create_diagnostics_bundle
from external_tools_gui import ExternalToolsPage
from knowledge_service import KnowledgeService
from knowledge_scheduler import KnowledgeScheduler
from knowledge_gui import KnowledgePage
from i18n import init_translator, t
from unityscraper.domains.library import LibraryService
from platform_support import open_path
from profile_gui import ProfileSavePage
from package_gui import PackageLabPage
from profile_manager import ProfileSaveManager
from setup_wizard import run_first_run_wizard
from title_catalog import TitleSuggestion, XboxUnityTitleCatalog
from ui_theme import (
    DEFAULT_ACCENT,
    DEFAULT_THEME,
    PALETTE,
    UI_FONT,
    apply_theme,
    text_options,
)
from unityscraper.app.desktop.command_palette import CommandPalette, PaletteEntry
from unityscraper.app.desktop.shell import (
    NotificationPanel,
    PageSpec,
    ShortcutSheet,
    Sidebar,
    StatusBar,
    ToastManager,
)
from unityscraper.core.config import read_config, update_config
from unityscraper.app.desktop.downloads_page import DownloadsPage, notify_check_results
from unityscraper.app.desktop.home_page import HomePage
from unityscraper.app.desktop.library_page import LibraryPage
from unityscraper.app.desktop.settings_page import SettingsPage
from unityscraper.core.db_backups import AutoBackupService
from unityscraper.core.notifications import NotificationService
from unityscraper.domains.library.update_watch import (
    UpdateWatchService,
    make_xboxunity_collector,
)
from unityscraper.domains.backups.watch_folders import WatchFolderService, WatchScanSummary
from updater import VersionChecker


T = TypeVar("T")
APP_VERSION = DISPLAY_VERSION
PROJECT_CREATOR = "TrapEmAll"
XEXTOOL_CREATOR = "xorloser"
LE_FLUFFIE_CREATOR = "Dalavin (DJ SkunkieButt)"
COMMUNITY_MESSAGE = (
    "UnityScraper is my way of giving back to the Xbox 360 community that has "
    "kept this console alive through curiosity, preservation, homebrew, and "
    "shared knowledge. Thank you to every developer, archivist, modder, tester, "
    "and player who continues to contribute. I hope this project makes your "
    "collection easier to care for and helps preserve a piece of gaming history "
    "for years to come."
)


def _open_path(path: Path) -> None:
    """Open a file or folder using the current operating system."""
    try:
        open_path(path)
    except (OSError, RuntimeError) as exc:
        messagebox.showerror("Unable to open", str(exc))


def navigation_shortcut(index: int) -> str | None:
    """Map the first ten navigation entries to Alt+1 through Alt+0."""
    if 1 <= index <= 9:
        return str(index)
    if index == 10:
        return "0"
    return None


class TitleAutocomplete(ttk.Frame):
    """Entry with a non-blocking local title suggestion popup."""

    def __init__(
        self,
        parent: tk.Misc,
        search: Callable[[str], list[TitleSuggestion]],
        on_select: Callable[[TitleSuggestion], None],
    ) -> None:
        super().__init__(parent)
        self.search = search
        self.on_select = on_select
        self.variable = tk.StringVar()
        self.suggestions: list[TitleSuggestion] = []
        self._search_job: str | None = None

        self.entry = ttk.Entry(self, textvariable=self.variable)
        self.entry.pack(fill=tk.X, expand=True)
        self.entry.bind("<KeyRelease>", self._key_released)
        self.entry.bind("<Down>", self._focus_suggestions)
        self.entry.bind("<Return>", self._accept_first)
        self.entry.bind("<Escape>", lambda _event: self.hide())
        self.entry.bind("<FocusOut>", self._queue_hide)

        self.popup = tk.Toplevel(self)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.configure(background=PALETTE.border)
        self.popup.transient(self.winfo_toplevel())
        self.listbox = tk.Listbox(
            self.popup,
            height=8,
            background=PALETTE.field,
            foreground=PALETTE.text,
            selectbackground=PALETTE.selection,
            selectforeground=PALETTE.selection_text,
            highlightthickness=1,
            highlightbackground=PALETTE.border,
            relief=tk.FLAT,
            font=(UI_FONT, 10),
            activestyle="none",
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<Return>", self._accept)
        self.listbox.bind("<ButtonRelease-1>", self._accept)
        self.listbox.bind("<Double-Button-1>", self._accept)
        self.listbox.bind("<Escape>", lambda _event: self.hide())
        self.listbox.bind("<FocusOut>", self._queue_hide)

    def _key_released(self, event: tk.Event[Any]) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape"}:
            return
        if self._search_job is not None:
            self.after_cancel(self._search_job)
        self._search_job = self.after(120, self._refresh)

    def _refresh(self) -> None:
        self._search_job = None
        self.suggestions = self.search(self.variable.get())
        self.listbox.delete(0, tk.END)
        for suggestion in self.suggestions:
            self.listbox.insert(tk.END, suggestion.label)
        if self.suggestions:
            self._show_popup()
        else:
            self.hide()

    def _show_popup(self) -> None:
        self.update_idletasks()
        width = max(self.entry.winfo_width(), 460)
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        height = min(8, len(self.suggestions)) * 26 + 2
        self.popup.geometry(f"{width}x{height}+{x}+{y}")
        self.popup.deiconify()
        self.popup.lift()

    def _focus_suggestions(self, _event: tk.Event[Any]) -> str:
        if not self.suggestions:
            self._refresh()
        if self.suggestions:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            self.listbox.focus_set()
        return "break"

    def _accept(self, _event: tk.Event[Any] | None = None) -> str:
        selection = self.listbox.curselection()
        if selection:
            suggestion = self.suggestions[int(selection[0])]
            self.variable.set(suggestion.label)
            self.on_select(suggestion)
        self.hide()
        self.entry.focus_set()
        return "break"

    def _accept_first(self, _event: tk.Event[Any]) -> str:
        if not self.suggestions:
            self._refresh()
        if self.suggestions:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            return self._accept()
        return "break"

    def _queue_hide(self, _event: tk.Event[Any]) -> None:
        self.after(100, self._hide_unfocused)

    def _hide_unfocused(self) -> None:
        focused = self.focus_get()
        if focused not in {self.entry, self.listbox}:
            self.hide()

    def hide(self) -> None:
        self.popup.withdraw()


class UnityScraperDesktop:
    """Main multi-page application window."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.library = LibraryService()
        self.knowledge = KnowledgeService()
        self.knowledge_scheduler = KnowledgeScheduler()
        self.backups = BackupService()
        self.profiles = ProfileSaveManager()
        self.collections = CollectionIntelligenceService()
        self.database = DatabaseManager()
        self.title_catalog = XboxUnityTitleCatalog()
        self.accessibility = AccessibilityService()
        self.accessibility_preferences = self.accessibility.get()
        self.notifications = NotificationService()
        self.current_game: str | None = None
        self.current_page = ""
        self._catalog_syncing = False
        self._catalog_events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._background_jobs = 0

        ensure_app_dirs()
        ensure_user_titleids_file()

        self.root.title(f"UnityScraper {APP_VERSION}")
        config = read_config()
        self.language = str(config.get("language", "en"))
        init_translator(self.language, LANGUAGE_PACKS_DIR)
        self._system_scaling = float(self.root.tk.call("tk", "scaling"))
        self.apply_ui_scale(float(config.get("ui_scale", 1.0)))
        self._restore_window(config.get("window"))
        self.root.minsize(1040, 680)
        self._set_icon()
        self._configure_style()
        self._build_ui(str(config.get("last_page", "home")))
        self._bind_shortcuts()
        self.root.protocol("WM_DELETE_WINDOW", self._close)

        run_first_run_wizard(self.root)
        self._refresh_library_page()
        # Re-read: the wizard may have just saved the catalog preference.
        if bool(read_config().get("sync_title_catalog_on_start", True)):
            self.root.after(750, self._start_catalog_sync_if_stale)
        self.root.after(1500, self._start_scheduled_tasks)

    # ----------------------------------------------------------- shell

    def _set_icon(self) -> None:
        self._icon_image: tk.PhotoImage | None = None
        self._brand_image: tk.PhotoImage | None = None
        icon = resource_path("assets", "UnityScraper.png")
        if not icon.exists():
            return
        try:
            self._icon_image = tk.PhotoImage(file=str(icon))
            self.root.iconphoto(True, self._icon_image)
            factor = max(1, self._icon_image.width() // 30)
            self._brand_image = self._icon_image.subsample(factor, factor)
        except tk.TclError:
            pass

    def _configure_style(self) -> None:
        config = read_config()
        apply_theme(
            self.root,
            theme=str(config.get("theme", DEFAULT_THEME)),
            accent=str(config.get("accent", DEFAULT_ACCENT)),
            high_contrast=bool(self.accessibility_preferences["high_contrast"]),
            large_text=bool(self.accessibility_preferences["large_text"]),
        )

    def apply_ui_scale(self, ui_scale: float) -> None:
        """Scale relative to the display's native DPI; 1.0 is the system default size."""
        scale = max(0.8, min(2.0, float(ui_scale)))
        if self.accessibility_preferences["large_text"]:
            scale = min(2.0, scale + 0.25)
        self.root.tk.call("tk", "scaling", self._system_scaling * scale)

    def rebuild(self) -> None:
        """Re-apply the theme and rebuild every widget on the current page."""
        self._configure_style()
        self._build_ui(self.current_page)

    def set_theme(self, theme: str, accent: str) -> None:
        """Persist and apply a theme, rebuilding the window so every widget picks it up."""
        update_config({"theme": theme, "accent": accent})
        self.rebuild()

    def _toggle_theme(self) -> None:
        config = read_config()
        current = str(config.get("theme", DEFAULT_THEME))
        self.set_theme(
            "light" if current == "dark" else "dark",
            str(config.get("accent", DEFAULT_ACCENT)),
        )

    def _build_pages(self) -> list[PageSpec]:
        entries: tuple[tuple[str, str, str, str, str], ...] = (
            ("home", t("nav_home"), "Overview", "⌂",
             "Recent activity, items needing attention, and shortcuts"),
            ("library", t("nav_library"), "Library", "▦",
             "Browse games, cover art, MediaIDs, and title updates"),
            ("add_games", t("nav_add_games"), "Library", "+",
             "Import TitleIDs from the XboxUnity catalog or a file"),
            ("downloads", t("nav_downloads"), "Library", "⇩",
             "Download tools, queue, and logs"),
            ("collections", t("nav_collections"), "Library", "▣",
             "Collection snapshots, matching, and repair previews"),
            ("backups", t("nav_backups"), "Console", "⛁",
             "Scan, install, export, and transfer backups"),
            ("profiles", t("nav_profiles"), "Console", "☺",
             "Profiles, saves, snapshots, and achievements"),
            ("package_lab", t("nav_package_lab"), "Console", "⬡",
             "Inspect STFS, SVOD, GDF/XISO, FATX, and GPD files"),
            ("external_tools", t("nav_tools"), "Console", "⚒",
             "Run community tools such as extract-xiso and Xenia"),
            ("knowledge", t("nav_knowledge"), "Knowledge", "✦",
             "Search sourced Xbox 360 knowledge"),
            ("community_hub", t("nav_community"), "Knowledge", "☷",
             "Unified search and community workspaces"),
            ("health", t("nav_health"), "System", "♥",
             "Find missing, empty, and duplicate archive files"),
            ("settings", t("nav_settings"), "System", "⚙",
             "Appearance, storage, and network settings"),
            ("about", t("nav_about"), "System", "ⓘ",
             "Diagnostics, storage, credits, and updates"),
        )
        pages = []
        for index, (key, label, group, icon, description) in enumerate(entries, start=1):
            shortcut = navigation_shortcut(index)
            pages.append(
                PageSpec(
                    key=key,
                    label=label,
                    group=group,
                    icon=icon,
                    show=lambda page=key: self.navigate(page),
                    description=description,
                    shortcut=f"Alt+{shortcut}" if shortcut else None,
                )
            )
        return pages

    def _build_ui(self, page_key: str) -> None:
        for child in self.root.winfo_children():
            if not isinstance(child, tk.Toplevel):
                child.destroy()
        self.pages = self._build_pages()
        self._pages_by_key = {page.key: page for page in self.pages}

        self._build_menubar()
        mode = "Portable" if portable_mode_enabled() else "Installed"
        self.status_bar = StatusBar(self.root, f"{mode}  ·  v{APP_VERSION}")
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_bar.set_jobs(self._background_jobs)

        body = ttk.Frame(self.root, style="Content.TFrame")
        body.pack(fill=tk.BOTH, expand=True)
        self.sidebar = Sidebar(
            body,
            self.pages,
            brand_image=self._brand_image,
            version=f"v{APP_VERSION}",
            show_hints=bool(self.accessibility_preferences["keyboard_hints"]),
        )
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        tk.Frame(body, width=1, background=PALETTE.border).pack(side=tk.LEFT, fill=tk.Y)

        main = ttk.Frame(body, style="Content.TFrame")
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._build_topbar(main)
        self.content = ttk.Frame(main, padding=(26, 4, 26, 18), style="Content.TFrame")
        self.content.pack(fill=tk.BOTH, expand=True)
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(1, weight=1)

        self.toasts = ToastManager(self.root)
        self.navigate(page_key if page_key in self._pages_by_key else "home")

    def _build_topbar(self, parent: ttk.Frame) -> None:
        bar = ttk.Frame(parent, padding=(26, 14, 26, 0), style="Content.TFrame")
        bar.pack(fill=tk.X)
        self.breadcrumb_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.breadcrumb_var, style="Small.TLabel").pack(side=tk.LEFT)

        self.notification_button = ttk.Button(
            bar, style="Header.TButton", command=self._open_notifications
        )
        self.notification_button.pack(side=tk.RIGHT)
        theme = str(read_config().get("theme", DEFAULT_THEME))
        ttk.Button(
            bar,
            text="☀  Light" if theme == "dark" else "☾  Dark",
            style="Header.TButton",
            command=self._toggle_theme,
        ).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(
            bar,
            text="⌕   Search or run a command…      Ctrl+P",
            style="Header.TButton",
            command=self.open_command_palette,
        ).pack(side=tk.RIGHT, padx=(0, 18))
        self._refresh_notification_badge()

    def _build_menubar(self) -> None:
        bar = ttk.Frame(self.root, style="Toolbar.TFrame", padding=(6, 2))
        bar.pack(side=tk.TOP, fill=tk.X)
        page = self._pages_by_key

        menu_definitions: tuple[
            tuple[str, tuple[tuple[str | None, Callable[[], Any] | None], ...]], ...
        ] = (
            ("File", (
                ("Add Games...", page["add_games"].show),
                ("Open Application Data", lambda: _open_path(BASE_DIR)),
                (None, None),
                ("Exit", self._close),
            )),
            ("View", tuple(
                (spec.label, spec.show)
                for spec in self.pages
                if spec.group in {"Overview", "Library", "Knowledge"}
            ) + (
                (None, None),
                ("Toggle Light/Dark Theme", self._toggle_theme),
            )),
            ("Tools", tuple(
                (spec.label, spec.show)
                for spec in self.pages
                if spec.group in {"Console", "System"} and spec.key != "about"
            )),
            ("Help", (
                ("Keyboard Shortcuts", self._show_shortcuts),
                ("Help & About", page["about"].show),
                ("Check for Updates", self._check_updates),
            )),
        )

        self._dropdown_menus: list[tk.Menu] = []
        for label, entries in menu_definitions:
            button = tk.Menubutton(
                bar,
                text=label,
                background=PALETTE.chrome,
                foreground=PALETTE.muted,
                activebackground=PALETTE.hover,
                activeforeground=PALETTE.text,
                borderwidth=0,
                relief=tk.FLAT,
                font=(UI_FONT, 9),
                padx=8,
                pady=3,
            )
            submenu = tk.Menu(
                button,
                tearoff=False,
                background=PALETTE.panel_alt,
                foreground=PALETTE.text,
                activebackground=PALETTE.selection,
                activeforeground=PALETTE.selection_text,
                borderwidth=0,
                font=(UI_FONT, 9),
            )
            for entry_label, command in entries:
                if entry_label is None:
                    submenu.add_separator()
                else:
                    submenu.add_command(label=entry_label, command=command)
            button.configure(menu=submenu)
            button.pack(side=tk.LEFT)
            self._dropdown_menus.append(submenu)
        self._menu = bar

    def _bind_shortcuts(self) -> None:
        for index, page in enumerate(self._build_pages(), start=1):
            shortcut = navigation_shortcut(index)
            if shortcut:
                self.root.bind(
                    f"<Alt-Key-{shortcut}>",
                    lambda _event, key=page.key: self.navigate(key),
                )
        self.root.bind("<Control-l>", lambda _event: self.navigate("library"))
        self.root.bind("<Control-k>", lambda _event: self.show_community_hub(focus_search=True))
        self.root.bind("<Control-comma>", lambda _event: self.navigate("settings"))
        self.root.bind("<F5>", lambda _event: self.navigate(self.current_page))
        self.root.bind("<F1>", lambda _event: self._show_shortcuts())
        self.root.bind("<Control-p>", lambda _event: self.open_command_palette())

    def _shortcut_list(self) -> list[tuple[str, str]]:
        shortcuts = [(page.shortcut, page.label) for page in self.pages if page.shortcut]
        return shortcuts + [
            ("Ctrl+L", "Library"),
            ("Ctrl+P", "Command palette: pages, actions, and games"),
            ("Ctrl+K", "Search everything (Community Hub)"),
            ("Ctrl+,", "Settings"),
            ("F5", "Reload the current page"),
            ("F1", "This list"),
        ]

    def _show_shortcuts(self) -> None:
        ShortcutSheet(self.root, self._shortcut_list())

    def open_command_palette(self) -> None:
        CommandPalette(self.root, self._palette_entries)

    def _palette_entries(self) -> list[PaletteEntry]:
        entries = [
            PaletteEntry(
                page.label, "Page", page.show,
                subtitle=page.description, keywords=page.group, shortcut=page.shortcut or "",
            )
            for page in self.pages
        ]
        config = read_config()
        theme = str(config.get("theme", DEFAULT_THEME))
        accent = str(config.get("accent", DEFAULT_ACCENT))
        actions: tuple[tuple[str, Callable[[], None], str, str], ...] = (
            ("Switch to light theme" if theme == "dark" else "Switch to dark theme",
             self._toggle_theme, "Appearance", ""),
            ("Use high-contrast theme", lambda: self.set_theme("high_contrast", accent),
             "Appearance accessibility", ""),
            ("Show keyboard shortcuts", self._show_shortcuts, "Help keys", "F1"),
            ("Show notifications", self._open_notifications, "Alerts history", ""),
            ("Refresh XboxUnity title catalog", self._start_catalog_sync, "Sync titles", ""),
            ("Check watched title updates", lambda: self.navigate("downloads"),
             "Watchlist downloads", ""),
            ("Open Advanced Tools", self._open_legacy_gui, "Collect metadata scraper", ""),
            ("Open GUI log", self._open_log, "Diagnostics", ""),
            ("Export diagnostics ZIP", self._export_diagnostics, "Support bundle", ""),
            ("Check for app updates", self._check_updates, "Release version", ""),
            ("Open application data folder", lambda: _open_path(BASE_DIR), "Storage", ""),
        )
        entries += [
            PaletteEntry(title, "Action", action, keywords=keywords, shortcut=shortcut)
            for title, action, keywords, shortcut in actions
        ]
        entries += [
            PaletteEntry(
                game.name, "Game", lambda titleid=game.titleid: self.open_game(titleid),
                subtitle=game.titleid, keywords=game.publisher or "",
            )
            for game in self.library.list_games()
        ]
        return entries

    def open_game(self, titleid: str) -> None:
        """Show one game selected in the library."""
        self.current_game = titleid
        self.navigate("library")

    def navigate(self, page_key: str) -> None:
        """Show a registered page and mark it active in the sidebar."""
        page = self._pages_by_key.get(page_key) or self._pages_by_key["home"]
        self.current_page = page.key
        self.sidebar.set_active(page.key)
        self.breadcrumb_var.set(f"{page.group}  /  {page.label}")
        getattr(self, f"show_{page.key}")()

    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _page_header(self, title: str, subtitle: str) -> None:
        header = ttk.Frame(self.content, style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(2, 16))
        ttk.Label(header, text=title, style="Header.TLabel").pack(anchor=tk.W)
        ttk.Label(header, text=subtitle, style="Subheader.TLabel").pack(
            anchor=tk.W, pady=(3, 0)
        )

    # ----------------------------------------------- status, jobs, notices

    def _on_ui_thread(self, callback: Callable[[], None]) -> bool:
        """Run ``callback`` on the Tk thread; returns False when called there already."""
        if threading.current_thread() is threading.main_thread():
            return False
        try:
            self.root.after(0, callback)
        except (RuntimeError, tk.TclError):
            pass  # The window closed while a worker was finishing.
        return True

    def set_status(self, text: str) -> None:
        """Update the window status bar; safe to call from worker threads."""
        if not self._on_ui_thread(lambda: self.set_status(text)):
            self.status_bar.set_text(text)

    def notify(
        self,
        level: str,
        title: str,
        message: str = "",
        *,
        source: str = "",
        toast: bool = True,
    ) -> None:
        """Record a notification and show a toast; safe to call from worker threads."""
        if self._on_ui_thread(
            lambda: self.notify(level, title, message, source=source, toast=toast)
        ):
            return
        self.notifications.add(level, title, message, source)
        if toast:
            self.toasts.show(level, title, message)
        self._refresh_notification_badge()

    def _refresh_notification_badge(self) -> None:
        count = self.notifications.unread_count()
        self.notification_button.configure(
            text=f"Notifications  {count}" if count else "Notifications"
        )

    def _open_notifications(self) -> None:
        NotificationPanel(
            self.root,
            self.notification_button,
            self.notifications,
            self._refresh_notification_badge,
        )

    def run_background(
        self,
        label: str,
        work: Callable[[], T],
        on_success: Callable[[T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Run ``work`` on a daemon thread; callbacks run on the Tk thread.

        Without ``on_error``, failures become an error notification.
        """
        self._background_jobs += 1
        self.status_bar.set_jobs(self._background_jobs)
        self.set_status(f"{label}…")

        def finish(result: Any, error: Exception | None) -> None:
            self._background_jobs -= 1
            self.status_bar.set_jobs(self._background_jobs)
            try:
                if error is not None:
                    self.set_status(f"{label} failed")
                    if on_error is not None:
                        on_error(error)
                    else:
                        self.notify("error", f"{label} failed", str(error), source=label)
                    return
                self.set_status(f"{label} finished")
                if on_success is not None:
                    on_success(result)
            except tk.TclError:
                pass  # The page that asked for the work was closed before it finished.

        def worker() -> None:
            try:
                result = work()
            except Exception as exc:
                self._on_ui_thread(lambda error=exc: finish(None, error))
            else:
                self._on_ui_thread(lambda: finish(result, None))

        threading.Thread(target=worker, name=label, daemon=True).start()

    # ------------------------------------------------- window persistence

    def _restore_window(self, saved: Any) -> None:
        geometry = "1320x840"
        zoomed = False
        if isinstance(saved, dict):
            match = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", str(saved.get("geometry", "")))
            if match:
                width, height, x, y = (int(value) for value in match.groups())
                screen_w = self.root.winfo_screenwidth()
                screen_h = self.root.winfo_screenheight()
                width, height = min(width, screen_w), min(height, screen_h)
                if 0 <= x < screen_w - 100 and 0 <= y < screen_h - 100:
                    geometry = f"{width}x{height}+{x}+{y}"
                else:
                    geometry = f"{width}x{height}"
            zoomed = bool(saved.get("zoomed"))
        self.root.geometry(geometry)
        if zoomed:
            try:
                self.root.state("zoomed")
            except tk.TclError:
                pass  # Not supported by every window manager.

    def _close(self) -> None:
        try:
            zoomed = self.root.state() == "zoomed"
            if zoomed:
                self.root.state("normal")
            update_config(
                {
                    "window": {"geometry": self.root.geometry(), "zoomed": zoomed},
                    "last_page": self.current_page,
                }
            )
        except (OSError, tk.TclError):
            pass  # Never block closing on a failed preference write.
        self.root.destroy()

    # ------------------------------------------------------------- pages

    def show_home(self) -> None:
        self._clear_content()
        self.home_page = HomePage(self)

    def show_backups(self) -> None:
        self._clear_content()
        self.backup_page = BackupPage(
            self.root,
            self.content,
            self.backups,
            self._page_header,
            notify=self.notify,
        )

    def show_external_tools(self) -> None:
        self._clear_content()
        self.external_tools_page = ExternalToolsPage(
            self.root,
            self.content,
            self._page_header,
            CONFIG_PATH,
        )

    def show_package_lab(self) -> None:
        self._clear_content()
        self.package_lab_page = PackageLabPage(
            self.root,
            self.content,
            self._page_header,
        )

    def show_profiles(self) -> None:
        self._clear_content()
        self.profile_save_page = ProfileSavePage(
            self.root,
            self.content,
            self.profiles,
            self._page_header,
            CONFIG_PATH,
        )

    def show_collections(self) -> None:
        self._clear_content()
        self.collection_page = CollectionPage(
            self.root,
            self.content,
            self.collections,
            self._page_header,
        )

    def show_library(self) -> None:
        self._clear_content()
        self.library_page = LibraryPage(self)

    def _refresh_library_page(self) -> None:
        page = getattr(self, "library_page", None)
        if page is not None and self.current_page == "library":
            page.refresh()

    def show_add_games(self) -> None:
        self._clear_content()
        self._page_header(
            "Add Games",
            "Import TitleIDs without editing JSON.txt by hand.",
        )

        body = ttk.Frame(self.content)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1, uniform="add")
        body.columnconfigure(1, weight=1, uniform="add")

        search = ttk.Frame(body, style="Card.TFrame", padding=18)
        search.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        search.columnconfigure(0, weight=1)
        ttk.Label(search, text="Find a game", style="CardHeading.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Label(
            search,
            text="Search the locally cached XboxUnity catalog by name or TitleID. "
            "Press Enter or pick a suggestion to add it.",
            style="CardMuted.TLabel",
            wraplength=420,
            justify=tk.LEFT,
        ).grid(row=1, column=0, sticky=tk.W, pady=(4, 12))
        self.title_autocomplete = TitleAutocomplete(
            search,
            self.title_catalog.search,
            self._accept_title_suggestion,
        )
        self.title_autocomplete.grid(row=2, column=0, sticky="ew")
        catalog_row = ttk.Frame(search, style="Card.TFrame")
        catalog_row.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        catalog_row.columnconfigure(0, weight=1)
        self.catalog_status_var = tk.StringVar(
            value=f"{self.title_catalog.count():,} XboxUnity titles cached locally"
        )
        ttk.Label(
            catalog_row, textvariable=self.catalog_status_var, style="CardMuted.TLabel"
        ).grid(row=0, column=0, sticky=tk.W)
        ttk.Button(
            catalog_row, text="Refresh catalog", command=self._start_catalog_sync
        ).grid(row=0, column=1, sticky=tk.E)

        selected = ttk.Frame(body, style="Card.TFrame", padding=18)
        selected.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        selected.columnconfigure(0, weight=1)
        selected.rowconfigure(2, weight=1)
        ttk.Label(selected, text="TitleIDs to add", style="CardHeading.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Label(
            selected,
            text="One per line, or separated by commas. Invalid entries are skipped.",
            style="CardMuted.TLabel",
        ).grid(row=1, column=0, sticky=tk.W, pady=(4, 10))
        self.add_titleids_text = tk.Text(
            selected, height=10, wrap=tk.WORD, padx=10, pady=8, **text_options()
        )
        self.add_titleids_text.grid(row=2, column=0, sticky="nsew")
        actions = ttk.Frame(selected, style="Card.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(
            actions, text="Import text file…", command=self._import_titleid_file
        ).pack(side=tk.LEFT)
        ttk.Button(
            actions, text="Save TitleIDs", style="Accent.TButton", command=self._save_titleids
        ).pack(side=tk.RIGHT)

        next_steps = ttk.Frame(body, style="Card.TFrame", padding=(18, 14))
        next_steps.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(20, 0))
        next_steps.columnconfigure(0, weight=1)
        ttk.Label(next_steps, text="Next step", style="CardHeading.TLabel").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Label(
            next_steps,
            text="After saving, open Advanced Tools and choose “Collect Metadata” to fetch "
            "covers and title updates from XboxUnity.",
            style="CardMuted.TLabel",
        ).grid(row=1, column=0, sticky=tk.W, pady=(4, 0))
        ttk.Button(
            next_steps, text="Open Advanced Tools", command=self._open_legacy_gui
        ).grid(row=0, column=1, rowspan=2, sticky=tk.E)

    def _accept_title_suggestion(self, suggestion: TitleSuggestion) -> None:
        current = self.add_titleids_text.get("1.0", tk.END).strip()
        separator = "\n" if current else ""
        self.add_titleids_text.insert(tk.END, f"{separator}{suggestion.titleid}")

    def _start_catalog_sync_if_stale(self) -> None:
        if self.title_catalog.is_stale():
            self._start_catalog_sync(silent=True)

    def _start_catalog_sync(self, silent: bool = False) -> None:
        if self._catalog_syncing:
            if not silent:
                self._set_catalog_status("XboxUnity catalog refresh already running")
            return
        self._catalog_syncing = True
        self._set_catalog_status("Starting XboxUnity catalog refresh...")

        def worker() -> None:
            try:
                result = self.title_catalog.sync(
                    progress=lambda page, pages, items: self._catalog_events.put(
                        ("progress", (page, pages, items))
                    )
                )
                self._catalog_events.put(("completed", result))
            except Exception as exc:
                self._catalog_events.put(("failed", str(exc)))

        threading.Thread(
            target=worker,
            name="xboxunity-catalog-sync",
            daemon=True,
        ).start()
        self.root.after(100, self._poll_catalog_events)

    def _poll_catalog_events(self) -> None:
        while True:
            try:
                event, value = self._catalog_events.get_nowait()
            except queue.Empty:
                break
            if event == "progress":
                page, pages, items = value
                self._set_catalog_status(
                    f"Caching XboxUnity titles: page {page}/{pages} ({items:,} titles)"
                )
            elif event == "completed":
                self._catalog_syncing = False
                self._set_catalog_status(
                    f"{value.items_upserted:,} XboxUnity titles cached locally"
                )
                self._refresh_library_page()
            elif event == "failed":
                self._catalog_syncing = False
                self._set_catalog_status(
                    f"Catalog refresh failed; using local cache ({value})"
                )
        if self._catalog_syncing:
            self.root.after(150, self._poll_catalog_events)

    def _set_catalog_status(self, text: str) -> None:
        if hasattr(self, "catalog_status_var"):
            self.catalog_status_var.set(text)

    def _start_scheduled_tasks(self) -> None:
        """Back up the database first if due, then run every other due schedule."""
        backups = AutoBackupService(self.database.db_path)
        if backups.schedule.is_due():
            # A clean restore point before syncs write, and no lock contention with them.
            self.run_background(
                "Automatic database backup",
                backups.run_if_due,
                lambda _backup: self._start_sync_tasks(),
                lambda error: (
                    self.notify("error", "Automatic database backup failed", str(error)),
                    self._start_sync_tasks(),
                ),
            )
        else:
            self._start_sync_tasks()

    def _start_sync_tasks(self) -> None:
        if self.knowledge_scheduler.is_due():
            self.run_background(
                "Scheduled knowledge refresh",
                self.knowledge_scheduler.run_if_due,
                lambda _result: self.notify(
                    "success", "Knowledge refreshed", source="Knowledge", toast=False
                ),
            )

        watchlist = UpdateWatchService(self.database.db_path)
        if watchlist.schedule().is_due():
            self.run_background(
                "Checking watched title updates",
                lambda: watchlist.run_if_due(make_xboxunity_collector()),
                lambda outcome: outcome and notify_check_results(self, outcome["result"]),
            )

        watch_folders = WatchFolderService(self.database.db_path)
        if watch_folders.schedule().is_due():
            self.run_background(
                "Scanning watch folders",
                lambda: watch_folders.run_if_due(self.backups.title_name),
                self._report_watch_folders,
            )

    def _report_watch_folders(self, summary: WatchScanSummary | None) -> None:
        if summary is None:
            return
        for result in summary.results:
            if result.new_items:
                self.notify(
                    "success",
                    f"New content in {result.folder.display_name}",
                    f"{len(result.new_items)} new item(s) found.",
                    source="Watch folders",
                )
        for folder, error in summary.failures:
            self.notify(
                "warning",
                f"Couldn't scan {folder.display_name}",
                error,
                source="Watch folders",
            )

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

        if valid:
            self.add_titleids_text.delete("1.0", tk.END)
        self.notify(
            "success" if valid else "info",
            f"Saved {len(valid)} TitleID(s)",
            f"{len(merged):,} TitleIDs are now in your import list.",
            source="Add games",
        )
        if invalid:
            self.notify(
                "warning",
                f"Skipped {len(invalid)} invalid entr{'y' if len(invalid) == 1 else 'ies'}",
                ", ".join(invalid[:20]),
                source="Add games",
            )

    def show_downloads(self) -> None:
        self._clear_content()
        self.downloads_page = DownloadsPage(self)

    def show_knowledge(self) -> None:
        self._clear_content()
        self._page_header(
            "Xbox 360 Knowledge",
            "Search games, releases, hardware, formats, repair notes, and source documents.",
        )
        self.knowledge_page = KnowledgePage(
            self.root,
            self.content,
            self.knowledge,
        )

    def show_community_hub(self, focus_search: bool = False) -> None:
        self._clear_content()
        self.community_hub_page = CommunityHubPage(
            self.root, self.content, self._page_header, self._navigate_search_result
        )
        if focus_search:
            self.root.after_idle(self.community_hub_page.focus_search)

    def _navigate_search_result(self, result: dict[str, Any]) -> None:
        """Open a unified-search result in its closest native workspace."""
        category = str(result.get("category", "")).casefold()
        target = str(result.get("target", ""))
        identifier = str(result.get("identifier", ""))
        if category == "game":
            self.current_game = identifier
            self.navigate("library")
            return
        if target.startswith("file:"):
            path = Path(target.removeprefix("file:"))
            _open_path(path.parent if path.is_file() else path)
            return
        if category in {"profile", "save", "achievement"}:
            self.navigate("profiles")
            self.profile_save_page.search_var.set(result.get("title", identifier))
            self.profile_save_page.refresh()
            return
        if category == "knowledge":
            self.navigate("knowledge")
            self.knowledge_page.search_var.set(result.get("title", ""))
            self.knowledge_page.refresh_results()
            return
        if target.startswith("structured:"):
            hub = self.community_hub_page
            hub.notebook.select(1)
            hub.knowledge_type.set(category)
            hub._refresh_knowledge()

    def show_health(self) -> None:
        self._clear_content()
        self._page_header(
            "Archive Health",
            "Find missing, zero-byte, and duplicate files in the local archive.",
        )

        panel = ttk.Frame(self.content)
        panel.grid(row=1, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(panel)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.health_button = ttk.Button(
            toolbar, text="Run archive scan", style="Accent.TButton", command=self._run_health_scan
        )
        self.health_button.pack(side=tk.LEFT)
        ttk.Label(
            toolbar,
            text="Checks every downloaded file recorded in the library database.",
            style="Muted.TLabel",
        ).pack(side=tk.LEFT, padx=(14, 0))

        self.health_metrics = ttk.Frame(panel)
        self.health_metrics.grid(row=1, column=0, sticky="ew", pady=(0, 14))

        self.health_text = tk.Text(panel, wrap=tk.WORD, padx=14, pady=12, **text_options())
        self.health_text.grid(row=2, column=0, sticky="nsew")
        self.health_text.insert(tk.END, "Run a scan to verify downloaded database records.\n")
        self.health_text.configure(state=tk.DISABLED)

    def _run_health_scan(self) -> None:
        self.health_button.configure(state=tk.DISABLED)

        def failed(error: Exception) -> None:
            if self.health_button.winfo_exists():
                self.health_button.configure(state=tk.NORMAL)
            self.notify("error", "Archive scan failed", str(error), source="Archive health")

        self.run_background(
            "Archive scan", self.library.scan_archive_health, self._show_health_report, failed
        )

    def _show_health_report(self, report: dict[str, Any]) -> None:
        problems = len(report["missing"]) + len(report["empty"])
        self.notify(
            "warning" if problems else "success",
            "Archive scan finished",
            f"{report['checked']:,} records checked, {problems} problem(s) found.",
            source="Archive health",
        )
        if not self.health_text.winfo_exists():
            return
        self.health_button.configure(state=tk.NORMAL)

        for child in self.health_metrics.winfo_children():
            child.destroy()
        metrics = (
            ("Records checked", report["checked"]),
            ("Healthy", len(report["healthy"])),
            ("Missing", len(report["missing"])),
            ("Empty", len(report["empty"])),
            ("Duplicate files", len(report["duplicate_files"])),
            ("Duplicate records", len(report["database_duplicates"])),
        )
        for column, (label, value) in enumerate(metrics):
            self.health_metrics.columnconfigure(column, weight=1, uniform="health")
            card = ttk.Frame(self.health_metrics, style="Card.TFrame", padding=(14, 10))
            card.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0))
            ttk.Label(card, text=f"{value:,}", style="Metric.TLabel").pack(anchor=tk.W)
            ttk.Label(card, text=label, style="CardMuted.TLabel").pack(anchor=tk.W)

        output: list[str] = []
        for category in ("missing", "empty"):
            if report[category]:
                output.append(f"{category.capitalize()} files")
                for item in report[category]:
                    output.append(
                        f"  • {item.get('titleid')} — {item.get('file_path') or item.get('reason')}"
                    )
                output.append("")
        if not output:
            output.append("No missing or empty files. Your archive matches the database.")

        self.health_text.configure(state=tk.NORMAL)
        self.health_text.delete("1.0", tk.END)
        self.health_text.insert(tk.END, "\n".join(output))
        self.health_text.configure(state=tk.DISABLED)

    def show_settings(self) -> None:
        self._clear_content()
        self.settings_page = SettingsPage(self)

    def show_about(self) -> None:
        self._clear_content()
        self._page_header(
            "Help & About",
            "Diagnostics, local storage, and project information.",
        )

        body = ttk.Frame(self.content)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=3, uniform="about")
        body.columnconfigure(1, weight=2, uniform="about")

        def card(column: int, row: int, title: str) -> ttk.Frame:
            frame = ttk.Frame(body, style="Card.TFrame", padding=18)
            frame.grid(
                row=row, column=column, sticky="nsew",
                padx=(0, 10) if column == 0 else (10, 0), pady=(0, 20),
            )
            ttk.Label(frame, text=title, style="CardHeading.TLabel").pack(anchor=tk.W, pady=(0, 8))
            return frame

        about = card(0, 0, f"UnityScraper {APP_VERSION}")
        ttk.Label(
            about,
            text=(
                f"Created and maintained by {PROJECT_CREATOR}. An Xbox 360 library, knowledge, "
                "title update, artwork, and backup manager, licensed under GPL-3.0-only.\n\n"
                f"Bundled XeXTool 6.3 by {XEXTOOL_CREATOR}. Profile and STFS design informed by "
                f"{LE_FLUFFIE_CREATOR}'s X360 library and Le Fluffie."
            ),
            style="Card.TLabel",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        storage = card(0, 1, "Local storage")
        ttk.Label(
            storage, text=describe_storage(), style="CardMuted.TLabel", justify=tk.LEFT
        ).pack(anchor=tk.W)
        ttk.Button(
            storage, text="Open application data", command=lambda: _open_path(BASE_DIR)
        ).pack(anchor=tk.W, pady=(12, 0))

        message = card(0, 2, f"A message from {PROJECT_CREATOR}")
        ttk.Label(
            message, text=COMMUNITY_MESSAGE, style="Card.TLabel", wraplength=560, justify=tk.LEFT
        ).pack(anchor=tk.W)
        ttk.Label(message, text=f"— {PROJECT_CREATOR}", style="CardMuted.TLabel").pack(
            anchor=tk.W, pady=(10, 0)
        )

        maintenance = card(1, 0, "Maintenance")
        for label, command, style in (
            ("Check for updates", self._check_updates, "Accent.TButton"),
            ("Export diagnostics ZIP", self._export_diagnostics, "TButton"),
            ("Database backups…", lambda: self.navigate("settings"), "TButton"),
            ("Keyboard shortcuts", self._show_shortcuts, "TButton"),
        ):
            ttk.Button(maintenance, text=label, style=style, command=command).pack(
                fill=tk.X, pady=3
            )

        links = card(1, 1, "Links")
        for label, url in (
            ("Documentation", "https://github.com/TrapEmAll/UnityScraper#readme"),
            ("GitHub project", "https://github.com/TrapEmAll/UnityScraper"),
            (f"{PROJECT_CREATOR} on GitHub", f"https://github.com/{PROJECT_CREATOR}"),
            (f"XeXTool credit: {XEXTOOL_CREATOR}", "https://github.com/XboxChef/XexToolGUI"),
            (f"Le Fluffie credit: {LE_FLUFFIE_CREATOR}", "https://github.com/mtolly/X360"),
        ):
            ttk.Button(
                links,
                text=f"{label}  ↗",
                style="Ghost.TButton",
                command=lambda target=url: webbrowser.open(target),
            ).pack(anchor=tk.W, pady=1)

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

    def _check_updates(self) -> None:
        checker = VersionChecker(timeout=10)

        def worker() -> None:
            has_update, info = checker.check_for_updates()
            self.root.after(0, lambda: self._show_update(checker, has_update, info))

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _show_update(self, checker: VersionChecker, has_update: bool, info: dict | None) -> None:
        if not has_update or not info:
            messagebox.showinfo("Updates", "You are running the latest release.", parent=self.root)
            return
        if not info.get("asset"):
            messagebox.showinfo(
                "Update available",
                VersionChecker.format_update_message(info),
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "Verified update available",
            f"UnityScraper {info['version']} is available for this platform.\n\n"
            "Download and verify the release package now?",
            parent=self.root,
        ):
            return
        destination = filedialog.askdirectory(parent=self.root, title="Choose download folder")
        if not destination:
            return

        def worker() -> None:
            try:
                package = checker.download_verified_update(info, destination)
            except Exception as exc:
                self.root.after(
                    0,
                    lambda error=exc: messagebox.showerror(
                        "Update failed", str(error), parent=self.root
                    ),
                )
            else:
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Update verified",
                        f"Verified package downloaded to:\n{package}\n\n"
                        "Close UnityScraper before installing it.",
                        parent=self.root,
                    ),
                )

        import threading

        threading.Thread(target=worker, daemon=True).start()

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
    root = tk.Tk(className="UnityScraper")
    UnityScraperDesktop(root)
    root.mainloop()


if __name__ == "__main__":
    main()

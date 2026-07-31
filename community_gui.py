"""Integrated desktop workspace for the community roadmap services."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from app_paths import DATABASE_PATH, DOWNLOADS_DIR, PROFILE_BACKUPS_DIR, executable_root
from backup_manager import FtpTarget
from community_services import (
    DASHBOARD_PRESETS,
    AccessibilityService,
    ArtworkService,
    ConsolePlanService,
    DashboardCompatibilityService,
    PackageWorkspaceService,
    PluginControlService,
    PreservationPlanningService,
    RecoveryService,
    StorageAndXboxService,
)
from profile_intelligence import ProfileIntelligenceService
from structured_knowledge import StructuredKnowledgeService
from unified_search import UnifiedSearchService


class CommunityHubPage:
    """One operational surface for cross-domain community workflows."""

    def __init__(self, root: tk.Tk, parent: ttk.Frame, page_header: Callable) -> None:
        self.root = root
        self.parent = parent
        self.search_service = UnifiedSearchService()
        self.structured = StructuredKnowledgeService()
        self.console_plans = ConsolePlanService()
        self.packages = PackageWorkspaceService()
        self.profiles = ProfileIntelligenceService()
        self.artwork = ArtworkService()
        self.preservation = PreservationPlanningService()
        self.storage = StorageAndXboxService()
        self.plugins = PluginControlService()
        self.recovery = RecoveryService()
        self.compatibility = DashboardCompatibilityService()
        self.accessibility = AccessibilityService()
        page_header("Community Hub", "Search, organize, preserve, and safely plan console changes.")
        self._build()

    def _build(self) -> None:
        notebook = ttk.Notebook(self.parent)
        notebook.grid(row=1, column=0, sticky="nsew")
        self.parent.rowconfigure(1, weight=1)
        for label, builder in (
            ("Search", self._build_search),
            ("Knowledge", self._build_knowledge),
            ("Console Sync", self._build_sync),
            ("Profiles", self._build_profiles),
            ("Preservation", self._build_preservation),
            ("Storage", self._build_storage),
            ("Plugins", self._build_plugins),
            ("Recovery", self._build_recovery),
            ("Compatibility", self._build_compatibility),
            ("Accessibility", self._build_accessibility),
        ):
            frame = ttk.Frame(notebook, padding=12)
            notebook.add(frame, text=label)
            builder(frame)

    def _build_search(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(frame, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search_entry.bind("<Return>", lambda _event: self._run_search())
        ttk.Button(frame, text="Search", command=self._run_search).grid(row=0, column=1)
        ttk.Label(frame, text="Games, knowledge, profiles, saves, achievements, files, and tools").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 10)
        )
        self.search_tree = ttk.Treeview(
            frame, columns=("category", "title", "details"), show="headings"
        )
        for column, heading, width in (
            ("category", "Type", 110), ("title", "Result", 280),
            ("details", "Details", 470),
        ):
            self.search_tree.heading(column, text=heading)
            self.search_tree.column(column, width=width, stretch=column != "category")
        self.search_tree.grid(row=2, column=0, columnspan=2, sticky="nsew")

    def focus_search(self) -> None:
        self.search_entry.focus_set()

    def _run_search(self) -> None:
        self._fill_tree(
            self.search_tree,
            self.search_service.search(self.search_var.get()),
            lambda row: (row["category"], row["title"], row["subtitle"]),
        )

    def _build_knowledge(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(controls, text="Extract Cached Articles", command=self._extract_knowledge).pack(side=tk.LEFT)
        self.knowledge_type = tk.StringVar(value="")
        ttk.Combobox(
            controls, textvariable=self.knowledge_type, state="readonly", width=20,
            values=("", "motherboard", "dvd_drive", "dashboard", "exploit", "error_code",
                    "file_format", "repair", "tool", "reference_article"),
        ).pack(side=tk.LEFT, padx=8)
        ttk.Button(controls, text="Refresh", command=self._refresh_knowledge).pack(side=tk.LEFT)
        self.knowledge_tree = ttk.Treeview(
            frame, columns=("type", "name", "source"), show="headings"
        )
        for column, heading, width in (("type", "Type", 130), ("name", "Name", 420),
                                       ("source", "Source", 220)):
            self.knowledge_tree.heading(column, text=heading)
            self.knowledge_tree.column(column, width=width)
        self.knowledge_tree.grid(row=1, column=0, sticky="nsew")

    def _extract_knowledge(self) -> None:
        self._run("Knowledge extraction", lambda: self.structured.extract_cached_documents())
        self._refresh_knowledge()

    def _refresh_knowledge(self) -> None:
        rows = self.structured.list_records(self.knowledge_type.get())
        self._fill_tree(self.knowledge_tree, rows,
                        lambda row: (row["record_type"], row["canonical_name"], row["source_name"]))

    def _build_sync(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        self.sync_root = tk.StringVar()
        self.sync_snapshot = tk.StringVar()
        self.sync_target = tk.StringVar()
        self.sync_dashboard = tk.StringVar(value="aurora")
        self._path_row(frame, 0, "Local content root", self.sync_root, directory=True)
        ttk.Label(frame, text="Console snapshot ID").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=self.sync_snapshot).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(frame, text="Dashboard").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(frame, textvariable=self.sync_dashboard, state="readonly",
                     values=tuple(DASHBOARD_PRESETS)).grid(row=2, column=1, sticky="w", pady=5)
        ttk.Label(frame, text="Saved console target ID (optional)").grid(
            row=3, column=0, sticky="w", pady=5
        )
        ttk.Entry(frame, textvariable=self.sync_target).grid(
            row=3, column=1, sticky="ew", pady=5
        )
        controls = ttk.Frame(frame)
        controls.grid(row=4, column=1, sticky="w", pady=10)
        ttk.Button(controls, text="Create Sync Preview", command=self._create_sync_plan).pack(
            side=tk.LEFT
        )
        self.queue_sync_button = ttk.Button(
            controls, text="Queue Previewed Uploads", command=self._queue_sync_plan,
            state=tk.DISABLED,
        )
        self.queue_sync_button.pack(side=tk.LEFT, padx=8)
        self.sync_output = self._output(frame, 5, 2)
        self.current_sync_plan_id: int | None = None

    def _create_sync_plan(self) -> None:
        result = self._run("Sync preview", lambda: self.console_plans.create_plan(
            self.sync_root.get(), int(self.sync_snapshot.get()), self.sync_dashboard.get()
        ))
        self._show_output(self.sync_output, result)
        if result is not None:
            self.current_sync_plan_id = int(result["plan_id"])
            self.queue_sync_button.configure(
                state=tk.NORMAL if result["summary"]["uploads"] else tk.DISABLED
            )

    def _queue_sync_plan(self) -> None:
        if self.current_sync_plan_id is None:
            return
        if not messagebox.askyesno(
            "Queue console uploads",
            "Queue every selected upload from this preview? Transfers will remain paused "
            "in the normal console queue until you run them.",
            parent=self.root,
        ):
            return
        target = self.sync_target.get().strip()
        result = self._run(
            "Queue sync plan",
            lambda: self.console_plans.queue_uploads(
                self.current_sync_plan_id, int(target) if target else None
            ),
        )
        self._show_output(self.sync_output, result)
        if result is not None:
            self.queue_sync_button.configure(state=tk.DISABLED)

    def _build_profiles(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        self.profile_id = tk.StringVar()
        ttk.Label(frame, text="Profile ID").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.profile_id).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Profile Dashboard", command=self._profile_dashboard).grid(
            row=0, column=2, padx=(8, 0)
        )
        self.package_path = tk.StringVar()
        self._path_row(frame, 1, "STFS package", self.package_path, directory=False)
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=1, sticky="w", pady=8)
        ttk.Button(buttons, text="Inspect Package", command=self._inspect_package).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Create Read-only Workspace", command=self._package_workspace).pack(
            side=tk.LEFT, padx=8
        )
        ttk.Button(buttons, text="Ownership Migration Preview", command=self._ownership_preview).pack(
            side=tk.LEFT
        )
        self.compare_left = tk.StringVar()
        self.compare_right = tk.StringVar()
        self._path_row(frame, 3, "Compare save A", self.compare_left, directory=False)
        self._path_row(frame, 4, "Compare save B", self.compare_right, directory=False)
        ttk.Button(frame, text="Compare Saves", command=self._compare_saves).grid(
            row=5, column=1, sticky="w", pady=8
        )
        self.profile_output = self._output(frame, 6, 3)

    def _profile_dashboard(self) -> None:
        self._show_output(self.profile_output, self._run(
            "Profile dashboard", lambda: self.profiles.profile_dashboard(self.profile_id.get())))

    def _inspect_package(self) -> None:
        self._show_output(self.profile_output, self._run(
            "Package inspection", lambda: self.packages.inspect(self.package_path.get())))

    def _package_workspace(self) -> None:
        destination = filedialog.askdirectory(parent=self.root, title="Choose package workspace")
        if destination:
            self._show_output(self.profile_output, self._run(
                "Package workspace", lambda: {"manifest": str(
                    self.packages.create_workspace(self.package_path.get(), destination))}))

    def _ownership_preview(self) -> None:
        self._show_output(self.profile_output, self._run(
            "Ownership preview", lambda: self.profiles.preview_ownership_migration(
                self.profile_id.get(), self.package_path.get())))

    def _compare_saves(self) -> None:
        self._show_output(self.profile_output, self._run(
            "Save comparison", lambda: self.profiles.compare_save_files(
                self.compare_left.get(), self.compare_right.get())))

    def _build_preservation(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        self.art_titleid = tk.StringVar()
        self.art_path = tk.StringVar()
        ttk.Label(frame, text="Artwork TitleID").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.art_titleid).grid(row=0, column=1, sticky="ew", pady=4)
        self._path_row(frame, 1, "Preferred artwork", self.art_path, directory=False)
        controls = ttk.Frame(frame)
        controls.grid(row=2, column=1, sticky="w", pady=8)
        ttk.Button(controls, text="Set Artwork", command=self._set_artwork).pack(side=tk.LEFT)
        ttk.Button(controls, text="Export Artwork", command=self._export_artwork).pack(side=tk.LEFT, padx=8)
        ttk.Button(controls, text="Audit Disc Sets", command=self._audit_discs).pack(side=tk.LEFT)
        self.dedup_root = tk.StringVar()
        self._path_row(frame, 3, "Duplicate scan root", self.dedup_root, directory=True)
        dedup_controls = ttk.Frame(frame)
        dedup_controls.grid(row=4, column=1, sticky="w", pady=8)
        ttk.Button(dedup_controls, text="Create Dedup Preview", command=self._dedup).pack(
            side=tk.LEFT
        )
        self.dedup_action_id = tk.StringVar()
        ttk.Label(dedup_controls, text="Action ID").pack(side=tk.LEFT, padx=(14, 4))
        ttk.Entry(dedup_controls, textvariable=self.dedup_action_id, width=8).pack(side=tk.LEFT)
        self.dedup_mode = tk.StringVar(value="quarantine")
        ttk.Combobox(
            dedup_controls, textvariable=self.dedup_mode, state="readonly", width=11,
            values=("quarantine", "hardlink"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(dedup_controls, text="Apply Safely", command=self._apply_dedup).pack(
            side=tk.LEFT
        )
        self.preservation_output = self._output(frame, 5, 3)

    def _set_artwork(self) -> None:
        self._show_output(self.preservation_output, self._run(
            "Artwork preference", lambda: self.artwork.set_preference(
                self.art_titleid.get(), self.art_path.get())))

    def _export_artwork(self) -> None:
        destination = filedialog.askdirectory(parent=self.root, title="Choose artwork export folder")
        if destination:
            self._show_output(self.preservation_output, self._run(
                "Artwork export", lambda: self.artwork.export(destination, "aurora")))

    def _audit_discs(self) -> None:
        self._show_output(self.preservation_output, self._run(
            "Disc set audit", self.preservation.audit_disc_sets))

    def _dedup(self) -> None:
        self._show_output(self.preservation_output, self._run(
            "Dedup preview", lambda: self.preservation.create_dedup_plan(self.dedup_root.get())))

    def _apply_dedup(self) -> None:
        if not messagebox.askyesno(
            "Apply duplicate action",
            "Revalidate this duplicate and move its original into the recovery quarantine?",
            parent=self.root,
        ):
            return
        self._show_output(self.preservation_output, self._run(
            "Duplicate action", lambda: self.preservation.apply_dedup_action(
                int(self.dedup_action_id.get()), self.dedup_mode.get())))

    def _build_storage(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        self.storage_path = tk.StringVar()
        self._path_row(frame, 0, "Mounted storage or image", self.storage_path, directory=False,
                       allow_directory=True)
        ttk.Button(frame, text="Read-only Storage Audit", command=self._storage_audit).grid(
            row=1, column=1, sticky="w", pady=8
        )
        self.xbox_root = tk.StringVar()
        self._path_row(frame, 2, "Original Xbox games root", self.xbox_root, directory=True)
        ttk.Button(frame, text="Scan Original Xbox Games", command=self._scan_xbox).grid(
            row=3, column=1, sticky="w", pady=8
        )
        self.storage_output = self._output(frame, 4, 3)

    def _storage_audit(self) -> None:
        self._show_output(self.storage_output, self._run(
            "Storage audit", lambda: self.storage.audit_storage(self.storage_path.get())))

    def _scan_xbox(self) -> None:
        self._show_output(self.storage_output, self._run(
            "Original Xbox scan", lambda: self.storage.scan_original_xbox(self.xbox_root.get())))

    def _build_plugins(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)
        self.plugin_root = tk.StringVar(value=str(executable_root() / "plugins"))
        self._path_row(frame, 0, "Plugin folder", self.plugin_root, directory=True)
        controls = ttk.Frame(frame)
        controls.grid(row=1, column=1, sticky="w", pady=8)
        ttk.Button(controls, text="Discover", command=self._discover_plugins).pack(side=tk.LEFT)
        ttk.Button(controls, text="Install or Update", command=self._install_plugin).pack(side=tk.LEFT, padx=8)
        ttk.Button(controls, text="Enable", command=lambda: self._set_plugin(True)).pack(side=tk.LEFT)
        ttk.Button(controls, text="Disable", command=lambda: self._set_plugin(False)).pack(side=tk.LEFT, padx=8)
        self.plugin_tree = ttk.Treeview(
            frame, columns=("id", "version", "enabled", "trusted", "permissions"), show="headings"
        )
        for column, label, width in (("id", "Plugin", 180), ("version", "Version", 90),
                                     ("enabled", "Enabled", 75), ("trusted", "Checksum", 90),
                                     ("permissions", "Permissions", 280)):
            self.plugin_tree.heading(column, text=label)
            self.plugin_tree.column(column, width=width)
        self.plugin_tree.grid(row=2, column=0, columnspan=3, sticky="nsew")
        self.plugin_rows: dict[str, dict[str, Any]] = {}

    def _discover_plugins(self) -> None:
        rows = self._run("Plugin discovery", lambda: self.plugins.discover(self.plugin_root.get()))
        if rows is None:
            return
        self.plugin_rows.clear()
        self.plugin_tree.delete(*self.plugin_tree.get_children())
        for row in rows:
            plugin_id = row["id"]
            self.plugin_rows[plugin_id] = row
            self.plugin_tree.insert("", tk.END, iid=plugin_id, values=(
                row.get("name", plugin_id), row.get("version", ""),
                "Yes" if row.get("enabled") else "No",
                "Trusted" if row.get("trusted") else "Review",
                ", ".join(row.get("permissions", [])),
            ))

    def _install_plugin(self) -> None:
        archive = filedialog.askopenfilename(
            parent=self.root, title="Choose a plugin ZIP", filetypes=(("ZIP archives", "*.zip"),)
        )
        if archive:
            self._run("Plugin installation", lambda: self.plugins.install_package(
                archive, self.plugin_root.get()))
            self._discover_plugins()

    def _set_plugin(self, enabled: bool) -> None:
        selection = self.plugin_tree.selection()
        if not selection:
            messagebox.showinfo("Plugins", "Select a plugin first.", parent=self.root)
            return
        plugin_id = selection[0]
        row = self.plugin_rows[plugin_id]
        manifest_path = Path(self.plugin_root.get()) / plugin_id / "plugin.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            entry = manifest_path.parent / manifest["entrypoint"]
            self.plugins.set_state(plugin_id, enabled, entry, row.get("permissions", []))
        except Exception as exc:
            messagebox.showerror("Plugins", str(exc), parent=self.root)
            return
        self._discover_plugins()

    def _build_recovery(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        controls = ttk.Frame(frame)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(controls, text="Scan Recovery State", command=self._scan_recovery).pack(side=tk.LEFT)
        ttk.Button(controls, text="Recover Selected", command=self._recover_selected).pack(side=tk.LEFT, padx=8)
        self.recovery_tree = ttk.Treeview(
            frame, columns=("type", "source", "detected"), show="headings"
        )
        for column, label, width in (("type", "Issue", 160), ("source", "Source", 500),
                                     ("detected", "Detected", 190)):
            self.recovery_tree.heading(column, text=label)
            self.recovery_tree.column(column, width=width)
        self.recovery_tree.grid(row=1, column=0, sticky="nsew")

    def _scan_recovery(self) -> None:
        roots = (DOWNLOADS_DIR, PROFILE_BACKUPS_DIR, DATABASE_PATH.parent)
        result = self._run("Recovery scan", lambda: self.recovery.scan(roots))
        if result is not None:
            self._refresh_recovery()

    def _refresh_recovery(self) -> None:
        self.recovery_tree.delete(*self.recovery_tree.get_children())
        for row in self.recovery.list_open():
            self.recovery_tree.insert("", tk.END, iid=str(row["id"]), values=(
                row["event_type"].replace("_", " ").title(), row["source"], row["detected_at"]
            ))

    def _recover_selected(self) -> None:
        selection = self.recovery_tree.selection()
        if not selection:
            messagebox.showinfo("Recovery", "Select a recovery item first.", parent=self.root)
            return
        result = self._run("Recovery", lambda: self.recovery.recover(int(selection[0])))
        if result:
            messagebox.showinfo("Recovery", result["action"], parent=self.root)
            self._refresh_recovery()

    def _build_compatibility(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        self.compat_dashboard = tk.StringVar(value="aurora")
        self.compat_host = tk.StringVar()
        self.compat_user = tk.StringVar(value="xbox")
        self.compat_password = tk.StringVar(value="xbox")
        for row, (label, variable, secret) in enumerate((
            ("Host", self.compat_host, False), ("Username", self.compat_user, False),
            ("Password", self.compat_password, True),
        )):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(frame, textvariable=variable, show="*" if secret else "").grid(
                row=row, column=1, sticky="ew", pady=4
            )
        ttk.Combobox(frame, textvariable=self.compat_dashboard, state="readonly",
                     values=tuple(DASHBOARD_PRESETS)).grid(row=3, column=1, sticky="w", pady=4)
        ttk.Button(frame, text="Run Read-only Compatibility Probe", command=self._probe).grid(
            row=4, column=1, sticky="w", pady=8
        )
        self.compat_output = self._output(frame, 5, 2)

    def _probe(self) -> None:
        target = FtpTarget(self.compat_host.get(), username=self.compat_user.get(),
                           password=self.compat_password.get())
        self._show_output(self.compat_output, self._run(
            "Dashboard probe", lambda: self.compatibility.probe(
                self.compat_dashboard.get(), target)))

    def _build_accessibility(self, frame: ttk.Frame) -> None:
        values = self.accessibility.get()
        self.access_vars: dict[str, tk.BooleanVar] = {}
        labels = {"large_text": "Large text", "high_contrast": "High contrast",
                  "reduced_motion": "Reduced motion", "keyboard_hints": "Keyboard hints"}
        for row, key in enumerate(labels):
            variable = tk.BooleanVar(value=values[key])
            self.access_vars[key] = variable
            ttk.Checkbutton(frame, text=labels[key], variable=variable,
                            command=lambda name=key, value=variable: self.accessibility.set(
                                name, value.get())).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Label(frame, text="Accessibility preferences are applied on the next application start.").grid(
            row=len(labels), column=0, sticky="w", pady=(14, 0)
        )

    def _path_row(self, frame: ttk.Frame, row: int, label: str, variable: tk.StringVar,
                  *, directory: bool, allow_directory: bool = False) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)
        def choose() -> None:
            if allow_directory:
                selected = filedialog.askopenfilename(parent=self.root, title=label)
                if not selected:
                    selected = filedialog.askdirectory(parent=self.root, title=label)
            elif directory:
                selected = filedialog.askdirectory(parent=self.root, title=label)
            else:
                selected = filedialog.askopenfilename(parent=self.root, title=label)
            if selected:
                variable.set(selected)
        ttk.Button(frame, text="Browse", command=choose).grid(row=row, column=2, padx=(8, 0), pady=4)

    @staticmethod
    def _output(frame: ttk.Frame, row: int, columnspan: int) -> tk.Text:
        frame.rowconfigure(row, weight=1)
        output = tk.Text(frame, wrap=tk.WORD, height=12, background="#070b08",
                         foreground="#eef4ef", insertbackground="#75d34b")
        output.grid(row=row, column=0, columnspan=columnspan, sticky="nsew", pady=(8, 0))
        output.configure(state=tk.DISABLED)
        return output

    @staticmethod
    def _show_output(widget: tk.Text, value: Any) -> None:
        if value is None:
            return
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, json.dumps(value, indent=2, default=str))
        widget.configure(state=tk.DISABLED)

    def _run(self, title: str, callback: Callable[[], Any]) -> Any:
        try:
            return callback()
        except Exception as exc:
            messagebox.showerror(title, str(exc), parent=self.root)
            return None

    @staticmethod
    def _fill_tree(tree: ttk.Treeview, rows: list[dict], values: Callable) -> None:
        tree.delete(*tree.get_children())
        for index, row in enumerate(rows):
            tree.insert("", tk.END, iid=str(index), values=values(row))

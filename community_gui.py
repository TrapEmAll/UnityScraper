"""Integrated desktop workspace for the community roadmap services."""

from __future__ import annotations

import json
import queue
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from app_paths import DATABASE_PATH, DOWNLOADS_DIR, PLUGINS_DIR, PROFILE_BACKUPS_DIR
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
from roadmap_services import (
    CorrectionPackageService,
    HardwareInventoryService,
    LibraryIntelligenceService,
    MetadataSnapshotService,
    PreservationReportService,
)
from platform_support import open_path
from structured_knowledge import StructuredKnowledgeService
from unified_search import UnifiedSearchService
from ui_theme import PALETTE


class CommunityHubPage:
    """One operational surface for cross-domain community workflows."""

    def __init__(
        self,
        root: tk.Tk,
        parent: ttk.Frame,
        page_header: Callable,
        navigate: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
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
        self.metadata_snapshots = MetadataSnapshotService()
        self.library_intelligence = LibraryIntelligenceService()
        self.preservation_reports = PreservationReportService()
        self.corrections = CorrectionPackageService()
        self.hardware = HardwareInventoryService()
        self.navigate = navigate
        self.search_rows: dict[str, dict[str, Any]] = {}
        self.task_events: queue.Queue[tuple[str, Future, Callable | None]] = queue.Queue()
        self.task_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="community")
        self.active_task: Future | None = None
        page_header("Community Hub", "Search, organize, preserve, and safely plan console changes.")
        self._build()
        self.root.after(100, self._poll_tasks)

    def _build(self) -> None:
        self.notebook = ttk.Notebook(self.parent)
        self.notebook.grid(row=1, column=0, sticky="nsew")
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
            ("Toolkit", self._build_toolkit),
            ("Accessibility", self._build_accessibility),
        ):
            frame = ttk.Frame(self.notebook, padding=12)
            self.notebook.add(frame, text=label)
            builder(frame)
        task_bar = ttk.Frame(self.parent)
        task_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.task_status = tk.StringVar(value="Ready")
        ttk.Label(task_bar, textvariable=self.task_status, style="Subheader.TLabel").pack(
            side=tk.LEFT
        )
        self.cancel_task_button = ttk.Button(
            task_bar, text="Cancel Pending Task", command=self._cancel_task, state=tk.DISABLED
        )
        self.cancel_task_button.pack(side=tk.RIGHT)

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
        self.search_tree.bind("<Double-1>", self._open_search_result)
        self.search_tree.bind("<Return>", self._open_search_result)

    def focus_search(self) -> None:
        self.search_entry.focus_set()

    def _run_search(self) -> None:
        rows = self.search_service.search(self.search_var.get())
        self.search_rows = {str(index): row for index, row in enumerate(rows)}
        self._fill_tree(self.search_tree, rows,
                        lambda row: (row["category"], row["title"], row["subtitle"]))

    def _open_search_result(self, _event: tk.Event | None = None) -> None:
        selection = self.search_tree.selection()
        if not selection:
            return
        row = self.search_rows.get(selection[0])
        if row is not None and self.navigate is not None:
            self.navigate(row)

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
        self._submit(
            "Knowledge extraction", self.structured.extract_cached_documents,
            lambda _result: self._refresh_knowledge(),
        )

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
        self.sync_snapshot_ids: dict[str, int] = {}
        self.sync_target_ids: dict[str, int] = {}
        self._path_row(frame, 0, "Local content root", self.sync_root, directory=True)
        ttk.Label(frame, text="Console snapshot").grid(row=1, column=0, sticky="w", pady=5)
        self.sync_snapshot_combo = ttk.Combobox(
            frame, textvariable=self.sync_snapshot, state="readonly"
        )
        self.sync_snapshot_combo.grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(frame, text="Dashboard").grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(frame, textvariable=self.sync_dashboard, state="readonly",
                     values=tuple(DASHBOARD_PRESETS)).grid(row=2, column=1, sticky="w", pady=5)
        ttk.Label(frame, text="Saved console target (optional)").grid(
            row=3, column=0, sticky="w", pady=5
        )
        self.sync_target_combo = ttk.Combobox(
            frame, textvariable=self.sync_target, state="readonly"
        )
        self.sync_target_combo.grid(
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
        ttk.Button(controls, text="Refresh Sources", command=self._refresh_sync_sources).pack(
            side=tk.LEFT
        )
        self.sync_output = self._output(frame, 5, 2)
        self.current_sync_plan_id: int | None = None
        self._refresh_sync_sources()

    def _refresh_sync_sources(self) -> None:
        snapshots = self.console_plans.list_snapshots()
        self.sync_snapshot_ids = {
            f"#{row['id']} | {row['captured_at']} | {row['root']} | {row['item_count']} items":
                int(row["id"])
            for row in snapshots
        }
        self.sync_snapshot_combo.configure(values=tuple(self.sync_snapshot_ids))
        if self.sync_snapshot.get() not in self.sync_snapshot_ids:
            self.sync_snapshot.set(next(iter(self.sync_snapshot_ids), ""))
        targets = self.console_plans.list_ftp_targets()
        self.sync_target_ids = {
            f"{row['name']} | {row['location']}": int(row["id"]) for row in targets
        }
        target_values = ("", *self.sync_target_ids)
        self.sync_target_combo.configure(values=target_values)
        if self.sync_target.get() not in target_values:
            self.sync_target.set("")

    def _create_sync_plan(self) -> None:
        root = self.sync_root.get()
        if self.sync_snapshot.get() not in self.sync_snapshot_ids:
            messagebox.showinfo(
                "Console sync", "Capture a console inventory snapshot first.", parent=self.root
            )
            return
        snapshot_id = self.sync_snapshot_ids[self.sync_snapshot.get()]
        dashboard = self.sync_dashboard.get()
        def completed(result: Any) -> None:
            self._show_output(self.sync_output, result)
            self.current_sync_plan_id = int(result["plan_id"])
            self.queue_sync_button.configure(
                state=tk.NORMAL if result["summary"]["uploads"] else tk.DISABLED
            )
        self._submit(
            "Sync preview",
            lambda: self.console_plans.create_plan(root, snapshot_id, dashboard),
            completed,
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
        target = self.sync_target_ids.get(self.sync_target.get())
        plan_id = self.current_sync_plan_id
        self._submit_output(
            "Queue sync plan", self.sync_output,
            lambda: self.console_plans.queue_uploads(
                plan_id, target
            ),
            lambda _result: self.queue_sync_button.configure(state=tk.DISABLED),
        )

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
        ttk.Button(buttons, text="Extract Supported Files", command=self._extract_package).pack(
            side=tk.LEFT, padx=(0, 8)
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
        profile_id = self.profile_id.get()
        self._submit_output("Profile dashboard", self.profile_output,
                            lambda: self.profiles.profile_dashboard(profile_id))

    def _inspect_package(self) -> None:
        package_path = self.package_path.get()
        self._submit_output("Package inspection", self.profile_output,
                            lambda: self.packages.inspect(package_path))

    def _package_workspace(self) -> None:
        destination = filedialog.askdirectory(parent=self.root, title="Choose package workspace")
        if destination:
            package_path = self.package_path.get()
            self._submit_output("Package workspace", self.profile_output, lambda: {
                "manifest": str(self.packages.create_workspace(
                    package_path, destination))})

    def _extract_package(self) -> None:
        destination = filedialog.askdirectory(
            parent=self.root, title="Choose read-only extraction folder"
        )
        if destination:
            package_path = self.package_path.get()
            self._submit_output(
                "Package extraction",
                self.profile_output,
                lambda: self.packages.extract_read_only(package_path, destination),
            )

    def _ownership_preview(self) -> None:
        profile_id = self.profile_id.get()
        package_path = self.package_path.get()
        self._submit_output("Ownership preview", self.profile_output,
                            lambda: self.profiles.preview_ownership_migration(
                                profile_id, package_path))

    def _compare_saves(self) -> None:
        left = self.compare_left.get()
        right = self.compare_right.get()
        self._submit_output("Save comparison", self.profile_output,
                            lambda: self.profiles.compare_save_files(left, right))

    def _build_preservation(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        self.art_titleid = tk.StringVar()
        self.art_path = tk.StringVar()
        self.art_region = tk.StringVar()
        self.art_language = tk.StringVar()
        self.art_preset = tk.StringVar(value="aurora")
        ttk.Label(frame, text="Artwork TitleID").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.art_titleid).grid(row=0, column=1, sticky="ew", pady=4)
        self._path_row(frame, 1, "Preferred artwork", self.art_path, directory=False)
        metadata = ttk.Frame(frame)
        metadata.grid(row=2, column=1, sticky="w", pady=4)
        ttk.Label(metadata, text="Region").pack(side=tk.LEFT)
        ttk.Entry(metadata, textvariable=self.art_region, width=9).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(metadata, text="Language").pack(side=tk.LEFT)
        ttk.Entry(metadata, textvariable=self.art_language, width=9).pack(side=tk.LEFT, padx=(4, 0))
        controls = ttk.Frame(frame)
        controls.grid(row=3, column=1, sticky="w", pady=8)
        ttk.Button(controls, text="Set Artwork", command=self._set_artwork).pack(side=tk.LEFT)
        ttk.Combobox(controls, textvariable=self.art_preset, state="readonly", width=10,
                     values=tuple(self.artwork.PRESETS)).pack(side=tk.LEFT, padx=8)
        ttk.Button(controls, text="Export Artwork", command=self._export_artwork).pack(side=tk.LEFT)
        ttk.Button(controls, text="Audit Disc Sets", command=self._audit_discs).pack(
            side=tk.LEFT, padx=8
        )
        self.dedup_root = tk.StringVar()
        self._path_row(frame, 4, "Duplicate scan root", self.dedup_root, directory=True)
        dedup_controls = ttk.Frame(frame)
        dedup_controls.grid(row=5, column=1, sticky="w", pady=8)
        ttk.Button(dedup_controls, text="Create Dedup Preview", command=self._dedup).pack(
            side=tk.LEFT
        )
        self.dedup_mode = tk.StringVar(value="quarantine")
        ttk.Combobox(
            dedup_controls, textvariable=self.dedup_mode, state="readonly", width=11,
            values=("quarantine", "hardlink"),
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(dedup_controls, text="Apply Safely", command=self._apply_dedup).pack(
            side=tk.LEFT
        )
        ttk.Button(dedup_controls, text="Restore Selected", command=self._restore_dedup).pack(
            side=tk.LEFT, padx=4
        )
        self.dedup_tree = ttk.Treeview(
            frame, columns=("duplicate", "size", "status"), show="headings", height=7
        )
        for column, label, width in (
            ("duplicate", "Duplicate file", 560), ("size", "Bytes", 100),
            ("status", "Status", 100),
        ):
            self.dedup_tree.heading(column, text=label)
            self.dedup_tree.column(column, width=width, stretch=column == "duplicate")
        self.dedup_tree.grid(row=6, column=0, columnspan=3, sticky="nsew")
        self.current_dedup_plan_id: int | None = None
        self.preservation_output = self._output(frame, 7, 3)

    def _set_artwork(self) -> None:
        titleid = self.art_titleid.get()
        path = self.art_path.get()
        region = self.art_region.get()
        language = self.art_language.get()
        self._submit_output("Artwork preference", self.preservation_output,
                            lambda: self.artwork.set_preference(
                                titleid, path, region=region, language=language))

    def _export_artwork(self) -> None:
        destination = filedialog.askdirectory(parent=self.root, title="Choose artwork export folder")
        if destination:
            preset = self.art_preset.get()
            self._submit_output("Artwork export", self.preservation_output,
                                lambda: self.artwork.export(destination, preset))

    def _audit_discs(self) -> None:
        self._submit_output("Disc set audit", self.preservation_output,
                            self.preservation.audit_disc_sets)

    def _dedup(self) -> None:
        root = self.dedup_root.get()
        def completed(result: Any) -> None:
            self.current_dedup_plan_id = int(result["plan_id"])
            self._refresh_dedup_actions()
        self._submit_output("Dedup preview", self.preservation_output,
                            lambda: self.preservation.create_dedup_plan(root), completed)

    def _refresh_dedup_actions(self) -> None:
        self.dedup_tree.delete(*self.dedup_tree.get_children())
        for row in self.preservation.list_dedup_actions(self.current_dedup_plan_id):
            status = row.get("recovery_status") or row["status"]
            self.dedup_tree.insert("", tk.END, iid=str(row["id"]), values=(
                row["duplicate_path"], row["size"], status,
            ))

    def _apply_dedup(self) -> None:
        selection = self.dedup_tree.selection()
        if not selection:
            messagebox.showinfo("Duplicate files", "Select a duplicate first.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Apply duplicate action",
            "Revalidate this duplicate and move its original into the recovery quarantine?",
            parent=self.root,
        ):
            return
        action_id = int(selection[0])
        mode = self.dedup_mode.get()
        self._submit_output("Duplicate action", self.preservation_output,
                            lambda: self.preservation.apply_dedup_action(action_id, mode),
                            lambda _result: self._refresh_dedup_actions())

    def _restore_dedup(self) -> None:
        selection = self.dedup_tree.selection()
        if not selection:
            messagebox.showinfo("Duplicate files", "Select a duplicate first.", parent=self.root)
            return
        action_id = int(selection[0])
        if not messagebox.askyesno(
            "Restore duplicate", "Restore the quarantined original file?", parent=self.root
        ):
            return
        self._submit_output("Duplicate restore", self.preservation_output,
                            lambda: self.preservation.restore_dedup_action(action_id),
                            lambda _result: self._refresh_dedup_actions())

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
        path = self.storage_path.get()
        self._submit_output("Storage audit", self.storage_output,
                            lambda: self.storage.audit_storage(path))

    def _scan_xbox(self) -> None:
        root = self.xbox_root.get()
        self._submit_output("Original Xbox scan", self.storage_output,
                            lambda: self.storage.scan_original_xbox(root))

    def _build_plugins(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(2, weight=1)
        self.plugin_root = tk.StringVar(value=str(PLUGINS_DIR))
        ttk.Label(frame, text="Managed plugin folder").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(frame, textvariable=self.plugin_root).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Button(frame, text="Open Folder", command=lambda: open_path(PLUGINS_DIR)).grid(
            row=0, column=2, padx=(8, 0), pady=4
        )
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
                                     ("permissions", "Requested access", 280)):
            self.plugin_tree.heading(column, text=label)
            self.plugin_tree.column(column, width=width)
        self.plugin_tree.grid(row=2, column=0, columnspan=3, sticky="nsew")
        self.plugin_rows: dict[str, dict[str, Any]] = {}

    def _discover_plugins(self) -> None:
        plugin_root = self.plugin_root.get()
        def completed(rows: Any) -> None:
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
        self._submit("Plugin discovery", lambda: self.plugins.discover(plugin_root), completed)

    def _install_plugin(self) -> None:
        archive = filedialog.askopenfilename(
            parent=self.root, title="Choose a plugin ZIP", filetypes=(("ZIP archives", "*.zip"),)
        )
        if archive:
            plugin_root = self.plugin_root.get()
            self._submit(
                "Plugin installation",
                lambda: self.plugins.install_package(archive, plugin_root),
                lambda _result: self._discover_plugins(),
            )

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
        self._submit("Recovery scan", lambda: self.recovery.scan(roots),
                     lambda _result: self._refresh_recovery())

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
        def completed(result: Any) -> None:
            messagebox.showinfo("Recovery", result["action"], parent=self.root)
            self._refresh_recovery()
        self._submit("Recovery", lambda: self.recovery.recover(int(selection[0])), completed)

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
        dashboard = self.compat_dashboard.get()
        target = FtpTarget(self.compat_host.get(), username=self.compat_user.get(),
                           password=self.compat_password.get())
        self._submit_output("Dashboard probe", self.compat_output,
                            lambda: self.compatibility.probe(dashboard, target))

    def _build_toolkit(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(8, weight=1)
        metadata = ttk.LabelFrame(frame, text="Portable metadata", padding=8)
        metadata.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(metadata, text="Export Snapshot", command=self._export_metadata_snapshot).pack(
            side=tk.LEFT
        )
        ttk.Button(metadata, text="Import Snapshot", command=self._import_metadata_snapshot).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(metadata, text="Audit Library", command=self._audit_library).pack(side=tk.LEFT)
        ttk.Button(metadata, text="Preservation Report", command=self._preservation_report).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(metadata, text="Export Corrections", command=self._export_corrections).pack(
            side=tk.LEFT
        )

        hardware = ttk.LabelFrame(frame, text="Console hardware record", padding=8)
        hardware.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        hardware.columnconfigure(1, weight=1)
        self.hardware_vars = {
            key: tk.StringVar() for key in (
                "label", "motherboard", "dvd_drive", "nand_type",
                "dashboard_version", "console_type", "notes",
            )
        }
        fields = (
            ("Record label", "label"), ("Motherboard", "motherboard"),
            ("DVD drive", "dvd_drive"), ("NAND", "nand_type"),
            ("Dashboard", "dashboard_version"), ("Console type", "console_type"),
            ("Notes", "notes"),
        )
        for row, (label, key) in enumerate(fields):
            ttk.Label(hardware, text=label).grid(row=row // 2, column=(row % 2) * 2,
                                                 sticky="w", padx=(0, 5), pady=3)
            ttk.Entry(hardware, textvariable=self.hardware_vars[key], width=28).grid(
                row=row // 2, column=(row % 2) * 2 + 1, sticky="ew", padx=(0, 12), pady=3
            )
        ttk.Button(hardware, text="Save Hardware Record", command=self._save_hardware).grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(6, 0)
        )
        self.toolkit_output = self._output(frame, 8, 3)

    def _export_metadata_snapshot(self) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Export metadata snapshot",
            defaultextension=".usmeta", filetypes=(("UnityScraper metadata", "*.usmeta"),),
        )
        if destination:
            self._submit_output("Metadata snapshot", self.toolkit_output,
                                lambda: self.metadata_snapshots.export(destination))

    def _import_metadata_snapshot(self) -> None:
        source = filedialog.askopenfilename(
            parent=self.root, title="Import metadata snapshot",
            filetypes=(("UnityScraper metadata", "*.usmeta"), ("All files", "*.*")),
        )
        if source:
            self._submit_output("Metadata import", self.toolkit_output,
                                lambda: self.metadata_snapshots.import_snapshot(source))

    def _audit_library(self) -> None:
        self._submit_output("Library intelligence", self.toolkit_output,
                            self.library_intelligence.audit)

    def _preservation_report(self) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Export preservation report",
            defaultextension=".html", filetypes=(("HTML report", "*.html"),),
        )
        if destination:
            self._submit_output("Preservation report", self.toolkit_output,
                                lambda: self.preservation_reports.export_html(destination))

    def _export_corrections(self) -> None:
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Export community corrections",
            defaultextension=".json", filetypes=(("JSON package", "*.json"),),
        )
        if destination:
            self._submit_output("Correction package", self.toolkit_output,
                                lambda: self.corrections.export(destination))

    def _save_hardware(self) -> None:
        values = {key: variable.get() for key, variable in self.hardware_vars.items()}
        label = values.pop("label")
        self._submit_output("Hardware record", self.toolkit_output,
                            lambda: self.hardware.save(label, **values))

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
        output = tk.Text(
            frame, wrap=tk.WORD, height=12, background=PALETTE.field,
            foreground=PALETTE.text, insertbackground=PALETTE.accent_hot,
            selectbackground=PALETTE.selection, relief=tk.FLAT,
            highlightthickness=1, highlightbackground=PALETTE.border,
        )
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

    def _submit_output(
        self,
        title: str,
        output: tk.Text,
        callback: Callable[[], Any],
        after: Callable[[Any], None] | None = None,
    ) -> None:
        def completed(value: Any) -> None:
            self._show_output(output, value)
            if after is not None:
                after(value)
        self._submit(title, callback, completed)

    def _submit(
        self,
        title: str,
        callback: Callable[[], Any],
        completed: Callable[[Any], None] | None = None,
    ) -> None:
        if self.active_task is not None and not self.active_task.done():
            messagebox.showinfo(
                "Task in progress", "Wait for the current Community Hub task to finish.",
                parent=self.root,
            )
            return
        future = self.task_executor.submit(callback)
        self.active_task = future
        self.task_status.set(f"Running: {title}")
        self.cancel_task_button.configure(state=tk.NORMAL)
        future.add_done_callback(
            lambda item: self.task_events.put((title, item, completed))
        )

    def _cancel_task(self) -> None:
        if self.active_task is None or self.active_task.done():
            return
        if self.active_task.cancel():
            self.task_status.set("Pending task cancelled")
        else:
            self.task_status.set("The running operation will finish safely")
        self.cancel_task_button.configure(state=tk.DISABLED)

    def _poll_tasks(self) -> None:
        if not self.notebook.winfo_exists():
            self.task_executor.shutdown(wait=False, cancel_futures=True)
            return
        while True:
            try:
                title, future, completed = self.task_events.get_nowait()
            except queue.Empty:
                break
            self.active_task = None
            self.cancel_task_button.configure(state=tk.DISABLED)
            if future.cancelled():
                self.task_status.set(f"Cancelled: {title}")
                continue
            try:
                result = future.result()
            except Exception as exc:
                self.task_status.set(f"Failed: {title}")
                messagebox.showerror(title, str(exc), parent=self.root)
            else:
                self.task_status.set(f"Completed: {title}")
                if completed is not None:
                    completed(result)
        self.root.after(100, self._poll_tasks)

    @staticmethod
    def _fill_tree(tree: ttk.Treeview, rows: list[dict], values: Callable) -> None:
        tree.delete(*tree.get_children())
        for index, row in enumerate(rows):
            tree.insert("", tk.END, iid=str(index), values=values(row))

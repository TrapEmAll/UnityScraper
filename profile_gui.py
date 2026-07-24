"""Dark desktop workspace for Xbox 360 profiles and save data."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable

from platform_support import open_path
from profile_manager import ProfileSaveManager, mask_identifier


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
        self.config_path = config_path
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.running = False
        self.profiles: dict[str, dict[str, Any]] = {}
        self.saves: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, dict[str, Any]] = {}

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
        notebook.add(inventory, text="Inventory")
        notebook.add(snapshots, text="Snapshots")
        self._build_inventory(inventory)
        self._build_snapshots(snapshots)

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

    def refresh(self) -> None:
        self._refresh_profiles()
        self._refresh_snapshots()

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
        self._refresh_saves()

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

"""Dark desktop workspace for Xbox 360 backup management."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from pathlib import PurePosixPath
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from backup_manager import (
    BackupItem,
    ExternalConverter,
    FtpBackupClient,
    FtpTarget,
    inspect_stfs,
)
from backup_service import BackupService
from console_sync import ConsoleSyncService


class BackupPage:
    """Build and coordinate the backup manager page inside the desktop shell."""

    def __init__(
        self,
        root: tk.Tk,
        parent: ttk.Frame,
        service: BackupService,
        page_header: Callable[[str, str], None],
    ):
        self.root = root
        self.parent = parent
        self.service = service
        self.console_sync = ConsoleSyncService(service.repository.db_path)
        self.items: dict[str, BackupItem] = {}
        self.busy = False

        page_header(
            "Backup Manager",
            "Inventory, verify, install, export, and transfer your own Xbox backups.",
        )
        self._build()

    def _build(self) -> None:
        body = ttk.Frame(self.parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        target_bar = ttk.LabelFrame(body, text="Target", padding=10)
        target_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        target_bar.columnconfigure(1, weight=1)
        ttk.Label(target_bar, text="Console, USB, or archive folder").grid(
            row=0, column=0, sticky=tk.W, padx=(0, 8)
        )
        self.target_var = tk.StringVar()
        ttk.Entry(target_bar, textvariable=self.target_var).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(target_bar, text="Browse", command=self._choose_target).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Button(
            target_bar,
            text="Scan",
            command=self.scan,
            style="Accent.TButton",
        ).grid(row=0, column=3, padx=(8, 0))

        notebook = ttk.Notebook(body)
        notebook.grid(row=1, column=0, sticky="nsew")
        self.library_tab = ttk.Frame(notebook, padding=10)
        self.transfer_tab = ttk.Frame(notebook, padding=10)
        self.converter_tab = ttk.Frame(notebook, padding=10)
        notebook.add(self.library_tab, text="Inventory")
        notebook.add(self.transfer_tab, text="Console Transfer")
        notebook.add(self.converter_tab, text="ISO Converter")
        self._build_inventory()
        self._build_transfer()
        self._build_converter()

        self.status_var = tk.StringVar(value="Choose a target folder to begin.")
        ttk.Label(body, textvariable=self.status_var, style="Subheader.TLabel").grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

    def _build_inventory(self) -> None:
        tab = self.library_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        columns = ("titleid", "format", "size", "status")
        self.tree = ttk.Treeview(tab, columns=columns, show="tree headings", selectmode="browse")
        self.tree.heading("#0", text="Game")
        self.tree.heading("titleid", text="TitleID")
        self.tree.heading("format", text="Format")
        self.tree.heading("size", text="Size")
        self.tree.heading("status", text="Status")
        self.tree.column("#0", width=250, minwidth=150)
        self.tree.column("titleid", width=90, anchor=tk.CENTER)
        self.tree.column("format", width=180)
        self.tree.column("size", width=90, anchor=tk.E)
        self.tree.column("status", width=90, anchor=tk.CENTER)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        controls = ttk.Frame(tab)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(
            controls, text="Install Package", command=self.install_package
        ).pack(side=tk.LEFT)
        ttk.Button(
            controls, text="Import ZIP", command=self.import_zip
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            controls, text="Export Selected", command=self.export_selected
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            controls, text="Verify Selected", command=self.verify_selected
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="Verify All", command=self.verify_all).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(controls, text="Export All", command=self.export_all).pack(
            side=tk.LEFT, padx=(8, 0)
        )

    def _build_transfer(self) -> None:
        tab = self.transfer_tab
        tab.columnconfigure(1, weight=1)
        labels = (
            ("Console address", "ftp_host_var", ""),
            ("Port", "ftp_port_var", "21"),
            ("Username", "ftp_user_var", "xbox"),
            ("Password", "ftp_password_var", ""),
            ("Content root", "ftp_content_var", "/Hdd1/Content/0000000000000000"),
            ("Games root", "ftp_games_var", "/Hdd1/Games"),
        )
        for row, (label, attribute, default) in enumerate(labels):
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
            variable = tk.StringVar(value=default)
            setattr(self, attribute, variable)
            entry = ttk.Entry(
                tab,
                textvariable=variable,
                show="*" if attribute == "ftp_password_var" else "",
            )
            entry.grid(row=row, column=1, sticky="ew", padx=(10, 0), pady=4)
        ttk.Label(
            tab,
            text="Credentials stay in memory and are not saved to the database.",
            style="Subheader.TLabel",
        ).grid(row=6, column=0, columnspan=2, sticky=tk.W, pady=(10, 8))
        controls = ttk.Frame(tab)
        controls.grid(row=7, column=0, columnspan=2, sticky=tk.W)
        ttk.Button(controls, text="Test Connection", command=self.test_ftp).pack(
            side=tk.LEFT
        )
        ttk.Button(
            controls,
            text="Queue & Upload",
            command=self.queue_upload,
            style="Accent.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(controls, text="Pause", command=self.pause_transfer).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(controls, text="Resume", command=self.resume_transfer).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(controls, text="Snapshot Console", command=self.snapshot_console).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(controls, text="Compare Latest", command=self.compare_console).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        limit_row = ttk.Frame(tab)
        limit_row.grid(row=8, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(limit_row, text="Bandwidth limit (KiB/s)").pack(side=tk.LEFT)
        self.ftp_limit_var = tk.StringVar(value="0")
        ttk.Spinbox(
            limit_row, from_=0, to=102400, textvariable=self.ftp_limit_var, width=10
        ).pack(side=tk.LEFT, padx=(8, 0))
        self.ftp_remote_hash_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            limit_row,
            text="Require remote SHA-256 when supported",
            variable=self.ftp_remote_hash_var,
        ).pack(side=tk.LEFT, padx=(18, 0))
        self.queue_var = tk.StringVar(value="Persistent queue: empty")
        ttk.Label(tab, textvariable=self.queue_var, style="Subheader.TLabel").grid(
            row=9, column=0, columnspan=2, sticky=tk.W, pady=(8, 0)
        )
        self._refresh_queue_status()

    def _build_converter(self) -> None:
        tab = self.converter_tab
        tab.columnconfigure(1, weight=1)
        self.converter_path_var = tk.StringVar()
        self.converter_args_var = tk.StringVar(value='"{input}" "{output}"')
        self.iso_var = tk.StringVar()
        self.converter_output_var = tk.StringVar()
        rows = (
            ("Converter executable", self.converter_path_var, self._choose_converter),
            ("Argument template", self.converter_args_var, None),
            ("Source ISO", self.iso_var, self._choose_iso),
            ("Output folder", self.converter_output_var, self._choose_converter_output),
        )
        for row, (label, variable, callback) in enumerate(rows):
            ttk.Label(tab, text=label).grid(row=row, column=0, sticky=tk.W, pady=5)
            ttk.Entry(tab, textvariable=variable).grid(
                row=row, column=1, sticky="ew", padx=(10, 8), pady=5
            )
            if callback:
                ttk.Button(tab, text="Browse", command=callback).grid(
                    row=row, column=2, pady=5
                )
        ttk.Label(
            tab,
            text=(
                "Use a converter you trust for images you own. "
                "Placeholders: {input} and {output}."
            ),
            style="Subheader.TLabel",
        ).grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(10, 8))
        ttk.Button(
            tab,
            text="Run Converter",
            command=self.run_converter,
            style="Accent.TButton",
        ).grid(row=5, column=0, columnspan=3, sticky=tk.W)

    def _choose_target(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Choose backup target")
        if selected:
            self.target_var.set(selected)

    def _choose_converter(self) -> None:
        selected = filedialog.askopenfilename(parent=self.root, title="Choose converter")
        if selected:
            self.converter_path_var.set(selected)

    def _choose_iso(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose Xbox ISO",
            filetypes=(("ISO images", "*.iso"), ("All files", "*.*")),
        )
        if selected:
            self.iso_var.set(selected)

    def _choose_converter_output(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Choose output folder")
        if selected:
            self.converter_output_var.set(selected)

    def _run(self, message: str, operation: Callable[[], object], done: Callable) -> None:
        if self.busy:
            messagebox.showinfo("Backup Manager", "Another operation is still running.")
            return
        self.busy = True
        self.status_var.set(message)

        def worker() -> None:
            try:
                result = operation()
            except Exception as exc:
                self.root.after(0, lambda error=exc: self._failed(error))
            else:
                self.root.after(0, lambda: self._finished(result, done))

        threading.Thread(target=worker, daemon=True).start()

    def _failed(self, error: Exception) -> None:
        self.busy = False
        self.status_var.set(f"Operation failed: {error}")
        messagebox.showerror("Backup Manager", str(error), parent=self.root)

    def _finished(self, result: object, done: Callable) -> None:
        self.busy = False
        done(result)

    def scan(self) -> None:
        target = self.target_var.get().strip()
        if not target:
            self._choose_target()
            target = self.target_var.get().strip()
        if target:
            self._run("Scanning backup target...", lambda: self.service.scan(target), self._scan_done)

    def _scan_done(self, result) -> None:
        self.items.clear()
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(result.items):
            key = str(index)
            self.items[key] = item
            self.tree.insert(
                "",
                tk.END,
                iid=key,
                text=item.name,
                values=(
                    item.title_id or "Unknown",
                    item.format,
                    self._size(item.size),
                    item.status.title(),
                ),
            )
        self.status_var.set(
            f"Found {len(result.items)} items using {self._size(result.total_size)}."
        )
        if result.warnings:
            messagebox.showwarning(
                "Scan completed with notes",
                "\n".join(result.warnings[:12]),
                parent=self.root,
            )

    def install_package(self) -> None:
        target = self._required_target()
        if not target:
            return
        source = filedialog.askopenfilename(parent=self.root, title="Choose STFS package")
        if source:
            self._run(
                "Installing and verifying package...",
                lambda: self.service.install_package(source, target),
                lambda result: self._operation_done(
                    f"Package {result.status}: {result.destination}", refresh=True
                ),
            )

    def import_zip(self) -> None:
        target = self._required_target()
        if not target:
            return
        source = filedialog.askopenfilename(
            parent=self.root,
            title="Choose package archive",
            filetypes=(("ZIP archives", "*.zip"),),
        )
        if source:
            self._run(
                "Inspecting and importing archive...",
                lambda: self.service.import_archive(source, target),
                lambda results: self._operation_done(
                    f"Imported {len(results)} supported packages.", refresh=True
                ),
            )

    def export_selected(self) -> None:
        item = self._selected_item()
        if not item:
            return
        destination = filedialog.askdirectory(parent=self.root, title="Choose export folder")
        if destination:
            self._run(
                "Exporting files and creating manifest...",
                lambda: self.service.export(item, destination),
                lambda path: self._operation_done(f"Export completed: {path}"),
            )

    def verify_selected(self) -> None:
        item = self._selected_item()
        if not item:
            return
        self._run(
            "Checking selected backup...",
            lambda: self.service.verify(item),
            self._verify_done,
        )

    def _verify_done(self, issues) -> None:
        if issues:
            self.status_var.set(f"Verification found {len(issues)} issue(s).")
            messagebox.showwarning("Verification", "\n".join(issues[:20]), parent=self.root)
        else:
            self.status_var.set("Verification completed with no structural issues.")
            messagebox.showinfo("Verification", "No structural issues found.", parent=self.root)

    def verify_all(self) -> None:
        if not self.items:
            messagebox.showinfo("Verification", "Scan a target first.", parent=self.root)
            return
        self._run(
            "Checking all inventoried backups...",
            lambda: self.service.verify_many(list(self.items.values())),
            self._verify_batch_done,
        )

    def _verify_batch_done(self, findings: list[dict]) -> None:
        self.status_var.set(
            f"Batch verification completed: {len(findings)} item(s) need attention."
        )
        if findings:
            messagebox.showwarning(
                "Batch verification",
                "\n".join(
                    f"{item['path']}: {', '.join(item['issues'])}" for item in findings[:15]
                ),
                parent=self.root,
            )

    def export_all(self) -> None:
        if not self.items:
            messagebox.showinfo("Export", "Scan a target first.", parent=self.root)
            return
        destination = filedialog.askdirectory(parent=self.root, title="Choose batch export folder")
        if destination:
            self._run(
                "Exporting all inventoried backups...",
                lambda: self.service.export_many(list(self.items.values()), destination),
                lambda paths: self._operation_done(f"Exported {len(paths)} item(s)."),
            )

    def _ftp_target(self) -> FtpTarget:
        host = self.ftp_host_var.get().strip()
        if not host:
            raise ValueError("Enter the console address")
        return FtpTarget(
            host=host,
            port=int(self.ftp_port_var.get().strip() or "21"),
            username=self.ftp_user_var.get(),
            password=self.ftp_password_var.get(),
            content_root=self.ftp_content_var.get().strip(),
            games_root=self.ftp_games_var.get().strip(),
        )

    def test_ftp(self) -> None:
        self._run(
            "Connecting to console...",
            lambda: FtpBackupClient(self._ftp_target()).test_connection(),
            lambda welcome: self._operation_done(f"Connected: {welcome}"),
        )

    def upload_ftp(self) -> None:
        source = filedialog.askopenfilename(parent=self.root, title="Choose STFS package")
        if source:
            self._run(
                "Uploading package to console...",
                lambda: self.service.upload_ftp(source, self._ftp_target()),
                lambda result: self._operation_done(
                    f"Upload completed: {result.destination}"
                ),
            )

    def queue_upload(self) -> None:
        source = filedialog.askopenfilename(parent=self.root, title="Choose STFS package")
        if not source:
            return
        try:
            package = inspect_stfs(source)
            remote = str(
                PurePosixPath(self.ftp_content_var.get().strip())
                / package.title_id
                / package.content_directory
                / Path(source).name
            )
            job_id = self.console_sync.enqueue(
                "upload",
                source,
                remote,
                bandwidth_limit=max(0, int(self.ftp_limit_var.get() or "0")) * 1024,
                verify_remote_hash=self.ftp_remote_hash_var.get(),
            )
        except Exception as exc:
            self._failed(exc)
            return
        self._refresh_queue_status()
        self._run(
            f"Transferring queued job {job_id}...",
            lambda: self.console_sync.run_job(job_id, self._ftp_target()),
            lambda result: self._sync_done(result),
        )

    def pause_transfer(self) -> None:
        self.console_sync.pause()
        self.status_var.set("Pause requested. Partial data will be kept for resume.")

    def resume_transfer(self) -> None:
        paused = [job for job in self.console_sync.list_jobs() if job["status"] == "paused"]
        if not paused:
            messagebox.showinfo("Console transfer", "No paused job is available.", parent=self.root)
            return
        job_id = int(paused[0]["id"])
        self.console_sync.resume(job_id)
        self._run(
            f"Resuming job {job_id}...",
            lambda: self.console_sync.run_job(job_id, self._ftp_target()),
            lambda result: self._sync_done(result),
        )

    def snapshot_console(self) -> None:
        self._run(
            "Reading console inventory...",
            lambda: self.console_sync.capture_inventory(self._ftp_target(), "/Hdd1"),
            lambda snapshot_id: self._operation_done(
                f"Read-only console snapshot {snapshot_id} saved."
            ),
        )

    def compare_console(self) -> None:
        snapshots = [
            item for item in self.console_sync.list_snapshots()
            if item["status"] == "completed"
        ]
        if not snapshots:
            messagebox.showinfo(
                "Console comparison", "Capture a console snapshot first.", parent=self.root
            )
            return
        local = filedialog.askdirectory(parent=self.root, title="Choose matching PC folder")
        if not local:
            return
        snapshot_id = int(snapshots[0]["id"])
        self._run(
            f"Comparing with snapshot {snapshot_id}...",
            lambda: self.console_sync.compare(local, snapshot_id),
            lambda result: messagebox.showinfo(
                "PC and console comparison",
                f"Only on PC: {len(result.only_on_pc)}\n"
                f"Only on console: {len(result.only_on_console)}\n"
                f"Different size: {len(result.size_mismatches)}\n"
                f"Matching: {len(result.matching)}",
                parent=self.root,
            ),
        )

    def _sync_done(self, result: dict) -> None:
        self._refresh_queue_status()
        self._operation_done(
            f"Transfer {result['status']}: {result['transferred_bytes']} / "
            f"{result['total_bytes']} bytes."
        )

    def _refresh_queue_status(self) -> None:
        jobs = self.console_sync.list_jobs()
        active = sum(job["status"] in {"queued", "transferring", "paused"} for job in jobs)
        self.queue_var.set(f"Persistent queue: {active} active, {len(jobs)} total")

    def run_converter(self) -> None:
        import shlex

        try:
            arguments = shlex.split(self.converter_args_var.get())
            converter = ExternalConverter(self.converter_path_var.get(), arguments)
        except Exception as exc:
            self._failed(exc)
            return
        self._run(
            "Running external converter...",
            lambda: converter.convert(self.iso_var.get(), self.converter_output_var.get()),
            lambda result: self._operation_done(
                f"Converter completed successfully (exit {result.returncode})."
            ),
        )

    def _selected_item(self) -> Optional[BackupItem]:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Backup Manager", "Select an inventory item first.")
            return None
        return self.items.get(selected[0])

    def _required_target(self) -> str:
        target = self.target_var.get().strip()
        if not target:
            messagebox.showinfo("Backup Manager", "Choose a target folder first.")
        return target

    def _operation_done(self, message: str, refresh: bool = False) -> None:
        self.status_var.set(message)
        messagebox.showinfo("Backup Manager", message, parent=self.root)
        if refresh:
            self.scan()

    @staticmethod
    def _size(value: int) -> str:
        amount = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if amount < 1024 or unit == "TB":
                return f"{amount:.1f} {unit}"
            amount /= 1024
        return f"{amount:.1f} TB"

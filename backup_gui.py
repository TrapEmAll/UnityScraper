"""Dark desktop workspace for Xbox 360 backup management."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from backup_manager import (
    BackupItem,
    ExternalConverter,
    FtpBackupClient,
    FtpTarget,
)
from backup_service import BackupService


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
            text="Upload Package",
            command=self.upload_ftp,
            style="Accent.TButton",
        ).pack(side=tk.LEFT, padx=(8, 0))

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
                self.root.after(0, lambda: self._failed(exc))
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

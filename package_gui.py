"""Unified desktop work surface for Xbox package and image formats."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from unityscraper.domains.packages import (
    edit_stfs_metadata,
    extract_fatx,
    extract_gdf,
    extract_stfs_files,
    extract_svod_payload,
    inspect_fatx,
    inspect_gdf,
    inspect_stfs,
    inspect_svod,
    list_stfs_entries,
    replace_fatx_file,
    replace_stfs_file,
    verify_stfs,
    verify_svod,
)
from unityscraper.domains.profiles.gpd import (
    parse_gpd,
    set_gpd_achievement_state,
    update_gpd_setting,
)


class PackageLabPage:
    """STFS, disc, FATX, and GPD workflows in one desktop page."""

    def __init__(
        self,
        root: tk.Misc,
        parent: ttk.Frame,
        page_header: Callable[[str, str], None],
    ) -> None:
        self.root = root
        self.parent = parent
        self.status = tk.StringVar(value="Ready")
        page_header(
            "Package Lab", "Xbox package, disc image, device image, and profile database tools."
        )
        self.notebook = ttk.Notebook(parent)
        self.notebook.grid(row=1, column=0, sticky="nsew")
        self._build_stfs_tab()
        self._build_disc_tab()
        self._build_fatx_tab()
        self._build_gpd_tab()
        ttk.Label(parent, textvariable=self.status, style="Statusbar.TLabel").grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

    def _build_stfs_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="STFS")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.stfs_path = tk.StringVar()
        self.stfs_summary = tk.StringVar(value="No package loaded")
        self._path_row(tab, self.stfs_path, self._open_stfs)
        toolbar = ttk.Frame(tab)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        for label, command in (
            ("Verify", self._verify_stfs),
            ("Extract", self._extract_stfs),
            ("Replace", self._replace_stfs),
            ("Edit name", self._edit_stfs_name),
        ):
            ttk.Button(toolbar, text=label, command=command).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(toolbar, textvariable=self.stfs_summary).pack(side=tk.RIGHT)
        self.stfs_tree = self._tree(tab, ("kind", "size", "blocks"), (100, 110, 100), row=2)

    def _build_disc_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="Disc / GoD")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(3, weight=1)
        self.disc_path = tk.StringVar()
        self._path_row(tab, self.disc_path, self._open_gdf)
        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        ttk.Button(actions, text="Open XISO", command=self._open_gdf).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(actions, text="Extract XISO", command=self._extract_gdf).pack(
            side=tk.LEFT, padx=(0, 18)
        )
        ttk.Button(actions, text="Open GoD", command=self._open_svod).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(actions, text="Verify GoD", command=self._verify_svod).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(actions, text="Extract GoD", command=self._extract_svod).pack(side=tk.LEFT)
        self.disc_summary = tk.StringVar(value="No image loaded")
        ttk.Label(tab, textvariable=self.disc_summary).grid(
            row=2, column=0, sticky=tk.W, pady=(0, 6)
        )
        self.disc_tree = self._tree(tab, ("kind", "size", "sector"), (100, 110, 100), row=3)

    def _build_fatx_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="FATX")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.fatx_path = tk.StringVar()
        self._path_row(tab, self.fatx_path, self._open_fatx)
        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        ttk.Button(actions, text="Extract", command=self._extract_fatx).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(actions, text="Replace", command=self._replace_fatx).pack(side=tk.LEFT)
        self.fatx_tree = self._tree(
            tab, ("partition", "kind", "size", "blocks"), (150, 90, 100, 90), row=2
        )

    def _build_gpd_tab(self) -> None:
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="GPD")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        self.gpd_path = tk.StringVar()
        self._path_row(tab, self.gpd_path, self._open_gpd)
        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        ttk.Button(actions, text="Edit selected", command=self._edit_gpd).pack(side=tk.LEFT)
        self.gpd_summary = tk.StringVar(value="No profile database loaded")
        ttk.Label(actions, textvariable=self.gpd_summary).pack(side=tk.RIGHT)
        self.gpd_tree = self._tree(tab, ("type", "state", "value"), (110, 150, 260), row=2)

    def _path_row(
        self, parent: ttk.Frame, variable: tk.StringVar, command: Callable[[], None]
    ) -> None:
        row = ttk.Frame(parent)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=variable, state="readonly").grid(row=0, column=0, sticky="ew")
        ttk.Button(row, text="Open", command=command).grid(row=0, column=1, padx=(8, 0))

    def _tree(
        self,
        parent: ttk.Frame,
        columns: tuple[str, ...],
        widths: tuple[int, ...],
        *,
        row: int,
    ) -> ttk.Treeview:
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(frame, columns=columns, show="tree headings", selectmode="browse")
        tree.heading("#0", text="Path")
        tree.column("#0", width=360, minwidth=180)
        for name, width in zip(columns, widths):
            tree.heading(name, text=name.title())
            tree.column(name, width=width, minwidth=70, stretch=name == columns[-1])
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        return tree

    def _run(self, action: Callable[[], None], success: str) -> None:
        self.root.configure(cursor="watch")
        self.status.set("Working...")
        self.root.update_idletasks()
        try:
            action()
        except Exception as exc:
            self.status.set("Operation failed")
            messagebox.showerror("Package Lab", str(exc), parent=self.root)
        else:
            self.status.set(success)
        finally:
            self.root.configure(cursor="")

    def _choose_file(self, title: str, patterns: tuple[tuple[str, str], ...]) -> str:
        return filedialog.askopenfilename(parent=self.root, title=title, filetypes=patterns)

    def _open_stfs(self) -> None:
        selected = self._choose_file("Open STFS package", (("Xbox packages", "*.*"),))
        if not selected:
            return
        self.stfs_path.set(selected)

        def action() -> None:
            package = inspect_stfs(selected)
            entries = list_stfs_entries(selected)
            self._clear_tree(self.stfs_tree)
            for entry in entries:
                self.stfs_tree.insert(
                    "",
                    tk.END,
                    iid=f"stfs:{entry.index}",
                    text=entry.path,
                    values=(
                        "Folder" if entry.is_directory else "File",
                        entry.size,
                        len(entry.blocks),
                    ),
                )
            self.stfs_summary.set(
                f"{package.title_id}  {package.content_label}  {len(entries):,} entries"
            )

        self._run(action, "STFS package loaded")

    def _verify_stfs(self) -> None:
        if not self.stfs_path.get():
            return

        def action() -> None:
            report = verify_stfs(self.stfs_path.get())
            self.stfs_summary.set(
                f"{report.valid_blocks:,} valid  {report.mismatched_blocks:,} mismatched  {report.unverifiable_blocks:,} missing"
            )

        self._run(action, "STFS verification completed")

    def _extract_stfs(self) -> None:
        destination = filedialog.askdirectory(parent=self.root, title="Extract STFS")
        if destination and self.stfs_path.get():
            selected = self._selected_path(self.stfs_tree)
            self._run(
                lambda: extract_stfs_files(
                    self.stfs_path.get(), destination, [selected] if selected else None
                ),
                "STFS extraction completed",
            )

    def _replace_stfs(self) -> None:
        internal = self._selected_path(self.stfs_tree)
        replacement = self._choose_file("Choose replacement", (("All files", "*.*"),))
        if not internal or not replacement or not self.stfs_path.get():
            return
        output = filedialog.asksaveasfilename(parent=self.root, title="Save edited package")
        if output:
            self._run(
                lambda: replace_stfs_file(
                    self.stfs_path.get(), internal, replacement, output=output
                ),
                "STFS replacement completed",
            )

    def _edit_stfs_name(self) -> None:
        if not self.stfs_path.get():
            return
        value = simpledialog.askstring("Display name", "Display name", parent=self.root)
        if value is None:
            return
        output = filedialog.asksaveasfilename(parent=self.root, title="Save edited package")
        if output:
            self._run(
                lambda: edit_stfs_metadata(
                    self.stfs_path.get(), {"display_name": value}, output=output
                ),
                "STFS metadata updated",
            )

    def _open_gdf(self) -> None:
        selected = self._choose_file(
            "Open XISO/GDF image", (("Disc images", "*.iso *.xiso *.gdf"), ("All files", "*.*"))
        )
        if not selected:
            return
        self.disc_path.set(selected)

        def action() -> None:
            image = inspect_gdf(selected)
            self._clear_tree(self.disc_tree)
            for index, entry in enumerate(image.entries):
                self.disc_tree.insert(
                    "",
                    tk.END,
                    iid=f"gdf:{index}",
                    text=entry.path,
                    values=(
                        "Folder" if entry.is_directory else "File",
                        entry.size,
                        entry.start_sector,
                    ),
                )
            self.disc_summary.set(f"XISO/GDF  {len(image.entries):,} entries")

        self._run(action, "Disc image loaded")

    def _extract_gdf(self) -> None:
        destination = filedialog.askdirectory(parent=self.root, title="Extract XISO/GDF")
        if destination and self.disc_path.get():
            self._run(
                lambda: extract_gdf(self.disc_path.get(), destination), "Disc extraction completed"
            )

    def _open_svod(self) -> None:
        selected = self._choose_file("Open Games on Demand header", (("GoD headers", "*.*"),))
        if not selected:
            return
        self.disc_path.set(selected)
        self._run(
            lambda: self.disc_summary.set(self._svod_summary(inspect_svod(selected))),
            "Games on Demand package loaded",
        )

    @staticmethod
    def _svod_summary(package) -> str:
        return f"GoD  {package.title_id}  {package.block_count:,} blocks  {package.data_file_count:,} files"

    def _verify_svod(self) -> None:
        if self.disc_path.get():

            def action() -> None:
                report = verify_svod(self.disc_path.get())
                self.disc_summary.set(
                    f"GoD  {report.valid_blocks:,} valid  {report.mismatched_blocks:,} mismatched"
                )

            self._run(action, "Games on Demand verification completed")

    def _extract_svod(self) -> None:
        if not self.disc_path.get():
            return
        output = filedialog.asksaveasfilename(
            parent=self.root, title="Save GoD payload", defaultextension=".iso"
        )
        if output:
            self._run(
                lambda: extract_svod_payload(self.disc_path.get(), output), "GoD payload extracted"
            )

    def _open_fatx(self) -> None:
        selected = self._choose_file(
            "Open FATX image", (("Device images", "*.img *.bin *.dd"), ("All files", "*.*"))
        )
        if not selected:
            return
        self.fatx_path.set(selected)

        def action() -> None:
            image = inspect_fatx(selected)
            self._clear_tree(self.fatx_tree)
            for index, entry in enumerate(image.entries):
                self.fatx_tree.insert(
                    "",
                    tk.END,
                    iid=f"fatx:{index}",
                    text=entry.path,
                    values=(
                        entry.partition,
                        "Folder" if entry.is_directory else "File",
                        entry.size,
                        len(entry.blocks),
                    ),
                )

        self._run(action, "FATX image loaded")

    def _extract_fatx(self) -> None:
        destination = filedialog.askdirectory(parent=self.root, title="Extract FATX")
        if destination and self.fatx_path.get():
            selected = self._selected_path(self.fatx_tree)
            self._run(
                lambda: extract_fatx(
                    self.fatx_path.get(), destination, [selected] if selected else None
                ),
                "FATX extraction completed",
            )

    def _replace_fatx(self) -> None:
        internal = self._selected_path(self.fatx_tree)
        replacement = self._choose_file("Choose replacement", (("All files", "*.*"),))
        if not internal or not replacement or not self.fatx_path.get():
            return
        output = filedialog.asksaveasfilename(parent=self.root, title="Save edited FATX image")
        if output:
            self._run(
                lambda: replace_fatx_file(
                    self.fatx_path.get(), internal, replacement, output=output
                ),
                "FATX replacement completed",
            )

    def _open_gpd(self) -> None:
        selected = self._choose_file(
            "Open GPD", (("Xbox profile databases", "*.gpd"), ("All files", "*.*"))
        )
        if not selected:
            return
        self.gpd_path.set(selected)

        def action() -> None:
            report = parse_gpd(selected)
            self._clear_tree(self.gpd_tree)
            for item in report.achievements:
                self.gpd_tree.insert(
                    "",
                    tk.END,
                    iid=f"achievement:{item.achievement_id}",
                    text=item.title,
                    values=("Achievement", item.state, item.gamerscore),
                )
            for item in report.settings:
                self.gpd_tree.insert(
                    "",
                    tk.END,
                    iid=f"setting:{item.setting_id}",
                    text=f"0x{item.setting_id:08X}",
                    values=("Setting", item.value_type, str(item.value)),
                )
            self.gpd_summary.set(
                f"{report.unlocked_count:,}/{len(report.achievements):,} achievements  {len(report.settings):,} settings"
            )

        self._run(action, "GPD loaded")

    def _edit_gpd(self) -> None:
        selection = self.gpd_tree.selection()
        if not selection or not self.gpd_path.get():
            return
        kind, raw_id = selection[0].split(":", 1)
        output = filedialog.asksaveasfilename(
            parent=self.root, title="Save edited GPD", defaultextension=".gpd"
        )
        if not output:
            return
        if kind == "achievement":
            state = simpledialog.askstring(
                "Achievement state",
                "locked, unlocked-offline, or unlocked-online",
                parent=self.root,
            )
            if state:
                self._run(
                    lambda: set_gpd_achievement_state(
                        self.gpd_path.get(), int(raw_id), state, output=output
                    ),
                    "Achievement updated",
                )
        else:
            value = simpledialog.askstring("Setting value", "Value", parent=self.root)
            if value is not None:
                self._run(
                    lambda: update_gpd_setting(
                        self.gpd_path.get(), int(raw_id), value, output=output
                    ),
                    "Setting updated",
                )

    @staticmethod
    def _clear_tree(tree: ttk.Treeview) -> None:
        tree.delete(*tree.get_children())

    @staticmethod
    def _selected_path(tree: ttk.Treeview) -> str:
        selection = tree.selection()
        return str(tree.item(selection[0], "text")) if selection else ""


__all__ = ["PackageLabPage"]

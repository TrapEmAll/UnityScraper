"""Desktop collection-intelligence workspace."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Callable

from collection_intelligence import (
    CollectionAnalysis,
    CollectionIntelligenceService,
    discover_storage_roots,
)


class CollectionPage:
    def __init__(
        self,
        root: tk.Tk,
        parent: ttk.Frame,
        service: CollectionIntelligenceService,
        page_header: Callable[[str, str], None],
    ) -> None:
        self.root = root
        self.parent = parent
        self.service = service
        self.analysis: CollectionAnalysis | None = None
        self.busy = False
        page_header(
            "Collection Intelligence",
            "Identify games, exact title-update compatibility, preservation matches, and repairs.",
        )
        self._build()

    def _build(self) -> None:
        body = ttk.Frame(self.parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        controls = ttk.Frame(body)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Collection source").grid(row=0, column=0, padx=(0, 8))
        self.source_var = tk.StringVar()
        ttk.Entry(controls, textvariable=self.source_var).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(controls, text="Discover", command=self.discover).grid(
            row=0, column=2, padx=(8, 0)
        )
        ttk.Button(controls, text="Browse", command=self.browse).grid(
            row=0, column=3, padx=(8, 0)
        )
        ttk.Button(
            controls, text="Analyze", command=self.analyze, style="Accent.TButton"
        ).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(controls, text="Import Aurora DB", command=self.import_aurora).grid(
            row=0, column=5, padx=(8, 0)
        )

        summary = ttk.Frame(body)
        summary.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self.score_var = tk.StringVar(value="Health: --")
        self.count_var = tk.StringVar(value="Games: --")
        self.issue_var = tk.StringVar(value="Issues: --")
        for variable in (self.score_var, self.count_var, self.issue_var):
            ttk.Label(summary, textvariable=variable, style="Metric.TLabel", padding=10).pack(
                side=tk.LEFT, padx=(0, 8)
            )

        columns = ("titleid", "mediaid", "format", "tu", "status")
        self.tree = ttk.Treeview(body, columns=columns, show="tree headings")
        self.tree.heading("#0", text="Game")
        for column, label in zip(
            columns, ("TitleID", "MediaID", "Format", "Title update", "Status")
        ):
            self.tree.heading(column, text=label)
        self.tree.column("#0", width=270)
        self.tree.column("titleid", width=90, anchor=tk.CENTER)
        self.tree.column("mediaid", width=90, anchor=tk.CENTER)
        self.tree.column("format", width=180)
        self.tree.column("tu", width=130)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.grid(row=2, column=0, sticky="nsew")

        actions = ttk.Frame(body)
        actions.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        action_specs = (
            ("Verify Selected", self.verify_selected),
            ("Repair Plan", self.repair_plan),
            ("Edit Metadata", self.edit_metadata),
            ("Export Manifest", self.export_manifest),
            ("Export HTML", self.export_html),
            ("Export Aurora", self.export_aurora),
            ("Export Provenance", self.export_provenance),
        )
        for column_index in range(4):
            actions.columnconfigure(column_index, weight=1)
        for index, (label, command) in enumerate(action_specs):
            ttk.Button(actions, text=label, command=command).grid(
                row=index // 4,
                column=index % 4,
                sticky="ew",
                padx=(0 if index % 4 == 0 else 8, 0),
                pady=(0 if index < 4 else 8, 0),
            )
        self.status_var = tk.StringVar(value="Choose a folder or discover mounted storage.")
        ttk.Label(body, textvariable=self.status_var, style="Subheader.TLabel").grid(
            row=4, column=0, sticky="ew", pady=(8, 0)
        )

    def discover(self) -> None:
        roots = discover_storage_roots()
        if roots:
            self.source_var.set(str(roots[0]))
            self.status_var.set(
                f"Found {len(roots)} mounted location(s); showing the strongest match."
            )
        else:
            self.status_var.set("No mounted collection root was detected.")

    def browse(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Choose collection root")
        if selected:
            self.source_var.set(selected)

    def analyze(self) -> None:
        source = self.source_var.get().strip()
        if not source:
            messagebox.showwarning("Collection source", "Choose a folder first.", parent=self.root)
            return
        self._run("Analyzing collection...", lambda: self.service.analyze(source))

    def import_aurora(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose an Aurora database",
            filetypes=(("SQLite databases", "*.db *.sqlite *.sqlite3"), ("All files", "*.*")),
        )
        if selected:
            self.source_var.set(selected)
            self._run("Reading Aurora database...", lambda: self.service.analyze_aurora(selected))

    def _run(self, message: str, operation) -> None:
        if self.busy:
            return
        self.busy = True
        self.status_var.set(message)

        def worker() -> None:
            try:
                result = operation()
            except Exception as exc:
                error = exc

                def report_error() -> None:
                    self._failed(error)

                self.root.after(0, report_error)
            else:
                self.root.after(0, lambda: self._finished(result))

        threading.Thread(target=worker, daemon=True).start()

    def _failed(self, error: Exception) -> None:
        self.busy = False
        self.status_var.set("Analysis failed.")
        messagebox.showerror("Collection analysis failed", str(error), parent=self.root)

    def _finished(self, analysis: CollectionAnalysis) -> None:
        self.busy = False
        self.analysis = analysis
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(analysis.result.items):
            match = analysis.compatibility[str(item.path)]
            self.tree.insert(
                "",
                tk.END,
                iid=str(index),
                text=item.name,
                values=(
                    item.title_id,
                    item.media_id,
                    item.format,
                    match.status,
                    item.status,
                ),
            )
        self.score_var.set(f"Health: {analysis.health_score}")
        self.count_var.set(f"Games: {len(analysis.result.items)}")
        self.issue_var.set(f"Issues: {len(analysis.issues)}")
        self.status_var.set(
            f"Snapshot {analysis.snapshot_id} saved. No repair action has been executed."
        )

    def _require_analysis(self) -> CollectionAnalysis | None:
        if self.analysis is None:
            messagebox.showinfo("Collection", "Analyze a collection first.", parent=self.root)
        return self.analysis

    def verify_selected(self) -> None:
        analysis = self._require_analysis()
        selected = self.tree.selection()
        if not analysis or not selected:
            return
        item = analysis.result.items[int(selected[0])]
        if not item.path.is_file():
            messagebox.showinfo(
                "Verification",
                "Select a package file to hash-match. Folder verification is represented in the scan.",
                parent=self.root,
            )
            return
        self._run_hash(item.path)

    def _run_hash(self, path: Path) -> None:
        self.status_var.set(f"Hashing {path.name}...")

        def worker() -> None:
            try:
                matches = self.service.hash_and_match(path)
            except Exception as exc:
                error = exc

                def report_error() -> None:
                    self._failed(error)

                self.root.after(0, report_error)
            else:
                self.root.after(
                    0,
                    lambda: self.status_var.set(
                        f"Verification complete: {len(matches)} Redump/No-Intro match(es)."
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def repair_plan(self) -> None:
        analysis = self._require_analysis()
        if analysis:
            plan_id = self.service.create_repair_plan(analysis)
            messagebox.showinfo(
                "Repair plan",
                f"Preview plan {plan_id} contains {len(analysis.issues)} proposed action(s).\n\n"
                "Nothing was changed.",
                parent=self.root,
            )

    def edit_metadata(self) -> None:
        analysis = self._require_analysis()
        selected = self.tree.selection()
        if not analysis or not selected:
            return
        item = analysis.result.items[int(selected[0])]
        if not item.title_id:
            messagebox.showinfo(
                "Metadata override", "This item needs a TitleID first.", parent=self.root
            )
            return
        value = simpledialog.askstring(
            "Local game name",
            f"Preferred local name for {item.title_id}:",
            initialvalue=item.name,
            parent=self.root,
        )
        if value and value.strip():
            self.service.set_override(item.title_id, "name", value.strip())
            item.name = value.strip()
            self.tree.item(selected[0], text=item.name)
            self.status_var.set(
                "Local override saved separately; imported source facts were not changed."
            )

    def export_manifest(self) -> None:
        analysis = self._require_analysis()
        if analysis:
            self.status_var.set(f"Manifest written to {self.service.export_manifest(analysis)}")

    def export_html(self) -> None:
        analysis = self._require_analysis()
        if analysis:
            self.status_var.set(f"HTML report written to {self.service.export_html(analysis)}")

    def export_provenance(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export provenance",
            defaultextension=".json",
            filetypes=(("JSON", "*.json"),),
        )
        if selected:
            self.status_var.set(
                f"Provenance written to {self.service.export_provenance(selected)}"
            )

    def export_aurora(self) -> None:
        analysis = self._require_analysis()
        if not analysis:
            return
        selected = filedialog.askdirectory(parent=self.root, title="Choose Aurora export root")
        if selected:
            try:
                output = self.service.export_aurora_layout(analysis, selected)
            except Exception as exc:
                self._failed(exc)
            else:
                self.status_var.set(f"Aurora layout exported to {output}")

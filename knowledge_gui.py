"""Tkinter knowledge browser used by the modern desktop interface."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from knowledge_service import KnowledgeService
from knowledge_scheduler import KnowledgeScheduler

TEXT = "#f2f5f2"
ACCENT = "#72e000"
BORDER = "#26352a"


class KnowledgePage:
    """Search, source-management, import, and conflict views."""

    def __init__(
        self,
        root: tk.Tk,
        parent: ttk.Frame,
        service: KnowledgeService,
    ) -> None:
        self.root = root
        self.parent = parent
        self.service = service
        self.scheduler = KnowledgeScheduler(service.database_path)
        self.status_var = tk.StringVar(value="Ready")
        self.search_var = tk.StringVar()
        self._build()

    def _build(self) -> None:
        body = ttk.Frame(self.parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        counts = self.service.counts()
        self.metric_vars: dict[str, tk.StringVar] = {}
        metrics = ttk.Frame(body)
        metrics.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        for column, (label, value) in enumerate(
            (
                ("Entities", counts["entities"]),
                ("Facts", counts["facts"]),
                ("Documents", counts["documents"]),
                ("Conflicts", counts["conflicts"]),
            )
        ):
            metric = ttk.LabelFrame(metrics, text=label, padding=(14, 7))
            metric.grid(row=0, column=column, sticky="ew", padx=(0, 8))
            metrics.columnconfigure(column, weight=1)
            variable = tk.StringVar(value=str(value))
            self.metric_vars[label.casefold()] = variable
            ttk.Label(
                metric,
                textvariable=variable,
                style="Metric.TLabel",
            ).pack()

        notebook = ttk.Notebook(body)
        notebook.grid(row=1, column=0, sticky="nsew")
        browse = ttk.Frame(notebook, padding=10)
        sources = ttk.Frame(notebook, padding=10)
        conflicts = ttk.Frame(notebook, padding=10)
        priorities = ttk.Frame(notebook, padding=10)
        notebook.add(browse, text="Browse")
        notebook.add(sources, text="Sources & Imports")
        notebook.add(conflicts, text="Conflicts")
        notebook.add(priorities, text="Priorities & Schedule")
        self._build_browse(browse)
        self._build_sources(sources)
        self._build_conflicts(conflicts)
        self._build_priorities(priorities)
        self.refresh()

    def _build_browse(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(parent)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure(0, weight=1)
        search = ttk.Entry(toolbar, textvariable=self.search_var)
        search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        search.bind("<Return>", lambda _event: self.refresh_results())
        ttk.Button(
            toolbar,
            text="Search",
            command=self.refresh_results,
            style="Accent.TButton",
        ).grid(row=0, column=1)

        split = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        split.grid(row=1, column=0, sticky="nsew")
        results = ttk.Frame(split)
        details = ttk.Frame(split)
        split.add(results, weight=3)
        split.add(details, weight=4)
        for panel in (results, details):
            panel.columnconfigure(0, weight=1)
            panel.rowconfigure(0, weight=1)

        self.result_tree = ttk.Treeview(
            results,
            columns=("type", "sources", "facts"),
            show="tree headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("#0", "Name", 310),
            ("type", "Type", 120),
            ("sources", "Sources", 65),
            ("facts", "Facts", 55),
        ):
            self.result_tree.heading(column, text=label)
            self.result_tree.column(column, width=width, minwidth=50)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        self.result_tree.bind("<<TreeviewSelect>>", self._show_details)
        scrollbar = ttk.Scrollbar(
            results, orient=tk.VERTICAL, command=self.result_tree.yview
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.result_tree.configure(yscrollcommand=scrollbar.set)

        self.detail_text = tk.Text(
            details,
            wrap=tk.WORD,
            background="#070b08",
            foreground=TEXT,
            insertbackground=ACCENT,
            selectbackground="#315f12",
            selectforeground=TEXT,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=12,
            pady=10,
        )
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        detail_scroll = ttk.Scrollbar(
            details, orient=tk.VERTICAL, command=self.detail_text.yview
        )
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.detail_text.configure(yscrollcommand=detail_scroll.set)

    def _build_sources(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        controls = ttk.Frame(parent)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        buttons = (
            ("Sync ConsoleMods IDs", self._sync_consolemods),
            ("Sync Reference Wikis", self._sync_wikis),
            ("Import Redump DAT", lambda: self._select_dat("redump")),
            ("Import No-Intro DAT", lambda: self._select_dat("no-intro")),
        )
        for index, (label, command) in enumerate(buttons):
            ttk.Button(
                controls,
                text=label,
                command=command,
                style="Accent.TButton" if index == 1 else "TButton",
            ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(
            controls,
            textvariable=self.status_var,
            style="Subheader.TLabel",
        ).pack(side=tk.RIGHT)

        self.source_tree = ttk.Treeview(
            parent,
            columns=("license", "documents", "facts", "status", "last_sync"),
            show="tree headings",
        )
        columns = (
            ("#0", "Source", 180),
            ("license", "License", 230),
            ("documents", "Documents", 75),
            ("facts", "Facts", 65),
            ("status", "Status", 80),
            ("last_sync", "Last sync", 160),
        )
        for column, label, width in columns:
            self.source_tree.heading(column, text=label)
            self.source_tree.column(column, width=width, minwidth=55)
        self.source_tree.grid(row=1, column=0, sticky="nsew")

    def _build_conflicts(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.conflict_tree = ttk.Treeview(
            parent,
            columns=("property", "existing", "incoming", "sources"),
            show="tree headings",
        )
        columns = (
            ("#0", "Entity", 190),
            ("property", "Property", 105),
            ("existing", "Existing claim", 220),
            ("incoming", "Incoming claim", 220),
            ("sources", "Sources", 180),
        )
        for column, label, width in columns:
            self.conflict_tree.heading(column, text=label)
            self.conflict_tree.column(column, width=width, minwidth=60)
        self.conflict_tree.grid(row=0, column=0, sticky="nsew")
        actions = ttk.Frame(parent)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(
            actions,
            text="Prefer Existing",
            command=lambda: self._resolve_selected_conflict("prefer_existing"),
        ).pack(side=tk.LEFT)
        ttk.Button(
            actions,
            text="Prefer Incoming",
            command=lambda: self._resolve_selected_conflict("prefer_incoming"),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            actions,
            text="Dismiss",
            command=lambda: self._resolve_selected_conflict("dismiss"),
        ).pack(side=tk.LEFT, padx=(8, 0))

    def _build_priorities(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        priority_controls = ttk.LabelFrame(
            parent, text="Field-specific source priority", padding=10
        )
        priority_controls.grid(row=0, column=0, sticky="ew")
        priority_controls.columnconfigure(1, weight=1)
        self.priority_property_var = tk.StringVar(value="publisher")
        self.priority_source_var = tk.StringVar()
        self.priority_value_var = tk.IntVar(value=100)
        ttk.Label(priority_controls, text="Fact property").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Entry(
            priority_controls, textvariable=self.priority_property_var
        ).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Label(priority_controls, text="Source").grid(
            row=1, column=0, sticky=tk.W, pady=(8, 0)
        )
        self.priority_source_combo = ttk.Combobox(
            priority_controls,
            textvariable=self.priority_source_var,
            state="readonly",
        )
        self.priority_source_combo.grid(
            row=1, column=1, sticky="ew", padx=8, pady=(8, 0)
        )
        ttk.Label(priority_controls, text="Priority").grid(
            row=2, column=0, sticky=tk.W, pady=(8, 0)
        )
        ttk.Spinbox(
            priority_controls,
            from_=1,
            to=1000,
            textvariable=self.priority_value_var,
            width=8,
        ).grid(row=2, column=1, sticky=tk.W, padx=8, pady=(8, 0))
        ttk.Button(
            priority_controls,
            text="Save Priority",
            command=self._save_priority,
            style="Accent.TButton",
        ).grid(row=2, column=2, pady=(8, 0))

        schedule = ttk.LabelFrame(parent, text="Automatic refresh", padding=10)
        schedule.grid(row=1, column=0, sticky="ew", pady=10)
        self.schedule_enabled_var = tk.BooleanVar()
        self.schedule_hours_var = tk.IntVar(value=168)
        ttk.Checkbutton(
            schedule,
            text="Refresh knowledge when the application starts and the interval is due",
            variable=self.schedule_enabled_var,
        ).pack(side=tk.LEFT)
        ttk.Label(schedule, text="Hours").pack(side=tk.LEFT, padx=(18, 6))
        ttk.Spinbox(
            schedule,
            from_=6,
            to=8760,
            textvariable=self.schedule_hours_var,
            width=7,
        ).pack(side=tk.LEFT)
        ttk.Button(
            schedule,
            text="Save Schedule",
            command=self._save_schedule,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.priority_tree = ttk.Treeview(
            parent,
            columns=("property", "source", "priority"),
            show="headings",
        )
        for column, label, width in (
            ("property", "Property", 180),
            ("source", "Source", 260),
            ("priority", "Priority", 90),
        ):
            self.priority_tree.heading(column, text=label)
            self.priority_tree.column(column, width=width, anchor=tk.W)
        self.priority_tree.grid(row=2, column=0, sticky="nsew")

    def refresh(self) -> None:
        counts = self.service.counts()
        for name, variable in self.metric_vars.items():
            variable.set(str(counts[name]))
        self.refresh_results()
        self.refresh_sources()
        self.refresh_conflicts()
        self.refresh_priorities()

    def refresh_results(self) -> None:
        self._clear_tree(self.result_tree)
        for row in self.service.search(self.search_var.get()):
            self.result_tree.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                text=row["canonical_name"],
                values=(
                    row["entity_type"].replace("_", " ").title(),
                    row["source_count"],
                    row["fact_count"],
                ),
            )

    def refresh_sources(self) -> None:
        self._clear_tree(self.source_tree)
        for row in self.service.list_sources():
            self.source_tree.insert(
                "",
                tk.END,
                text=row["name"],
                values=(
                    row["license_name"] or "See source",
                    row["document_count"],
                    row["fact_count"],
                    row["last_status"] or "Never",
                    row["last_sync"] or "",
                ),
            )

    def refresh_conflicts(self) -> None:
        self._clear_tree(self.conflict_tree)
        for row in self.service.list_conflicts():
            sources = (
                f"{row.get('existing_source') or 'Unknown'} / "
                f"{row.get('incoming_source') or 'Unknown'}"
            )
            self.conflict_tree.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                text=row["canonical_name"],
                values=(
                    row["property"],
                    row["existing_value"],
                    row["incoming_value"],
                    sources,
                ),
            )

    def refresh_priorities(self) -> None:
        sources = self.service.list_sources()
        self.priority_sources = {
            str(row["name"]): int(row["id"]) for row in sources
        }
        names = list(self.priority_sources)
        self.priority_source_combo.configure(values=names)
        if names and self.priority_source_var.get() not in self.priority_sources:
            self.priority_source_var.set(names[0])
        self.priority_tree.delete(*self.priority_tree.get_children())
        for row in self.service.list_priorities():
            if not row.get("property"):
                continue
            self.priority_tree.insert(
                "",
                tk.END,
                values=(
                    row["property"],
                    row["source_name"],
                    row["priority"],
                ),
            )
        state = self.scheduler.status()
        self.schedule_enabled_var.set(bool(state.get("enabled")))
        self.schedule_hours_var.set(int(state.get("interval_hours") or 168))

    def _save_priority(self) -> None:
        source_id = self.priority_sources.get(self.priority_source_var.get())
        if source_id is None:
            return
        try:
            self.service.set_source_priority(
                source_id,
                self.priority_property_var.get(),
                int(self.priority_value_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Priority not saved", str(exc), parent=self.root)
            return
        self.status_var.set("Source priority saved")
        self.refresh_priorities()

    def _save_schedule(self) -> None:
        try:
            self.scheduler.configure(
                self.schedule_enabled_var.get(),
                int(self.schedule_hours_var.get()),
            )
        except Exception as exc:
            messagebox.showerror("Schedule not saved", str(exc), parent=self.root)
            return
        self.status_var.set("Knowledge refresh schedule saved")
        self.refresh_priorities()

    def _resolve_selected_conflict(self, resolution: str) -> None:
        selection = self.conflict_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Resolve conflict", "Select a conflict first.", parent=self.root
            )
            return
        try:
            self.service.resolve_conflict(int(selection[0]), resolution)
        except Exception as exc:
            messagebox.showerror("Conflict not resolved", str(exc), parent=self.root)
            return
        self.status_var.set("Conflict decision recorded")
        self.refresh()

    def _show_details(self, _event: tk.Event[Any] | None = None) -> None:
        selection = self.result_tree.selection()
        if not selection:
            return
        details = self.service.entity_details(int(selection[0]))
        if not details:
            return
        entity = details["entity"]
        lines = [
            entity["canonical_name"],
            entity["entity_type"].replace("_", " ").title(),
            "",
            "IDENTIFIERS",
        ]
        for identifier in details["identifiers"]:
            source = identifier.get("source_name") or "Unknown source"
            lines.append(
                f"{identifier['identifier_type']}: "
                f"{identifier['identifier_value']}  [{source}]"
            )
        lines.extend(("", "FACTS AND CITATIONS"))
        for fact in details["facts"]:
            value = fact["value"]
            if fact["property"] == "article_text" and len(value) > 12000:
                value = value[:12000] + "\n\n[Article preview truncated]"
            lines.extend(
                (
                    "",
                    fact["property"].replace("_", " ").upper(),
                    value,
                    f"Source: {fact['source_name']}",
                )
            )
            if fact.get("source_url"):
                lines.append(f"Reference: {fact['source_url']}")
        self.detail_text.configure(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert(tk.END, "\n".join(lines))
        self.detail_text.configure(state=tk.DISABLED)

    def _sync_consolemods(self) -> None:
        from knowledge_sync import sync_consolemods_knowledge

        self._run_job("Syncing ConsoleMods IDs...", sync_consolemods_knowledge)

    def _sync_wikis(self) -> None:
        from knowledge_sync import sync_reference_wikis

        self._run_job("Syncing reference wikis...", sync_reference_wikis)

    def _select_dat(self, source_kind: str) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title=f"Select {source_kind} XML DAT",
            filetypes=(("XML DAT files", "*.dat *.xml"), ("All files", "*.*")),
        )
        if not path:
            return
        self._run_job(
            f"Importing {source_kind} DAT...",
            lambda: self._import_dat(Path(path), source_kind),
        )

    @staticmethod
    def _import_dat(path: Path, source_kind: str) -> dict[str, Any]:
        from knowledge_sync import import_dat_knowledge

        return import_dat_knowledge(path, source_kind)

    def _run_job(self, label: str, operation: Any) -> None:
        self.status_var.set(label)

        def worker() -> None:
            try:
                result = operation()
            except Exception as exc:
                self.root.after(
                    0,
                    lambda error=str(exc): self._job_failed(error),
                )
                return
            self.root.after(0, lambda: self._job_finished(result))

        threading.Thread(target=worker, daemon=True).start()

    def _job_finished(self, result: Any) -> None:
        self.status_var.set("Completed")
        self.refresh()
        messagebox.showinfo(
            "Knowledge import complete",
            f"The source import completed.\n\n{result}",
            parent=self.root,
        )

    def _job_failed(self, error: str) -> None:
        self.status_var.set("Failed")
        self.refresh_sources()
        messagebox.showerror("Knowledge import failed", error, parent=self.root)

    @staticmethod
    def _clear_tree(tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

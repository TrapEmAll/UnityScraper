"""Desktop Tool Center for trusted Xbox 360 community utilities."""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from app_paths import resource_path
from external_tools import (
    ExternalToolError,
    ExternalToolRunner,
    ToolLaunch,
    ToolResult,
    format_command,
    split_arguments,
)
from tool_catalog import ToolCatalog, ToolDefinition, ToolOperation
from ui_theme import PALETTE


XEXTOOL_PRESETS = {
    "Extended information": '-l "{input}"',
    "Basic information": '"{input}"',
    "Custom arguments": "",
}
XEXTOOL_CREDIT = "XeXTool 6.3 by xorloser"


def bundled_xextool_path() -> Path | None:
    """Return the packaged XeXTool executable when it is usable."""
    if os.name != "nt":
        return None
    candidate = resource_path("assets", "tools", "xextool", "xextool.exe")
    return candidate if candidate.is_file() else None


class ExternalToolsPage:
    """Configure, discover, and run the supported community tool catalog."""

    def __init__(
        self,
        root: tk.Tk,
        parent: ttk.Frame,
        page_header: Callable[[str, str], None],
        config_path: Path,
    ) -> None:
        self.root = root
        self.parent = parent
        self.catalog = ToolCatalog(config_path)
        self.runner = ExternalToolRunner()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.running = False
        self.tools_by_name = {tool.name: tool for tool in self.catalog.definitions()}
        page_header(
            "Tool Center",
            "Run trusted Xbox utilities from one workspace and keep their output with your library.",
        )
        self._build()

    def _build(self) -> None:
        body = ttk.Frame(self.parent)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        setup = ttk.LabelFrame(body, text="Tool Setup", padding=14)
        setup.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        setup.columnconfigure(1, weight=1)

        first = self.catalog.get("xextool")
        self.tool_type_var = tk.StringVar(value=first.name)
        self.executable_var = tk.StringVar()
        self.operation_var = tk.StringVar()
        self.arguments_var = tk.StringVar()
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.timeout_var = tk.IntVar(value=600)
        self.credit_var = tk.StringVar()
        self.risk_var = tk.StringVar()

        ttk.Label(setup, text="Tool").grid(row=0, column=0, sticky=tk.W, pady=4)
        tool_box = ttk.Combobox(
            setup,
            textvariable=self.tool_type_var,
            values=tuple(self.tools_by_name),
            state="readonly",
            width=25,
        )
        tool_box.grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=4)
        tool_box.bind("<<ComboboxSelected>>", self._tool_changed)
        ttk.Label(setup, textvariable=self.credit_var, style="Subheader.TLabel").grid(
            row=0, column=2, sticky=tk.E, pady=4
        )
        self.source_button = ttk.Button(setup, text="Source", command=self._open_source)
        self.source_button.grid(row=0, column=3, padx=(6, 0), pady=4)

        self._path_row(setup, 1, "Executable", self.executable_var, self._choose_executable)
        ttk.Button(setup, text="Detect", command=self._detect_executable).grid(
            row=1, column=3, padx=(6, 0), pady=4
        )

        ttk.Label(setup, text="Operation").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.operation_box = ttk.Combobox(
            setup, textvariable=self.operation_var, state="readonly", width=25
        )
        self.operation_box.grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=4)
        self.operation_box.bind("<<ComboboxSelected>>", self._operation_changed)
        ttk.Label(setup, textvariable=self.risk_var, style="Subheader.TLabel").grid(
            row=2, column=2, columnspan=2, sticky=tk.E, pady=4
        )

        self.input_label = ttk.Label(setup, text="Input path")
        self.input_label.grid(row=3, column=0, sticky=tk.W, pady=4)
        self.input_entry = ttk.Entry(setup, textvariable=self.input_var)
        self.input_entry.grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(10, 8), pady=4
        )
        self.input_button = ttk.Button(setup, text="Browse", command=self._choose_input)
        self.input_button.grid(row=3, column=3, pady=4)

        self.output_label = ttk.Label(setup, text="Output path")
        self.output_label.grid(row=4, column=0, sticky=tk.W, pady=4)
        self.output_entry = ttk.Entry(setup, textvariable=self.output_var)
        self.output_entry.grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(10, 8), pady=4
        )
        self.output_button = ttk.Button(setup, text="Browse", command=self._choose_output)
        self.output_button.grid(row=4, column=3, pady=4)

        ttk.Label(setup, text="Arguments").grid(row=5, column=0, sticky=tk.W, pady=4)
        self.arguments_entry = ttk.Entry(setup, textvariable=self.arguments_var)
        self.arguments_entry.grid(
            row=5, column=1, columnspan=3, sticky="ew", padx=(10, 0), pady=4
        )

        ttk.Label(setup, text="Timeout seconds").grid(row=6, column=0, sticky=tk.W, pady=4)
        ttk.Spinbox(
            setup, from_=1, to=86400, textvariable=self.timeout_var, width=10
        ).grid(row=6, column=1, sticky=tk.W, padx=(10, 0), pady=4)

        controls = ttk.Frame(setup)
        controls.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        self.run_button = ttk.Button(
            controls, text="Run Tool", command=self.run, style="Accent.TButton"
        )
        self.run_button.pack(side=tk.LEFT)
        ttk.Button(controls, text="Cancel", command=self.cancel).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(controls, text="Clear Output", command=self.clear_output).pack(
            side=tk.RIGHT
        )

        output_panel = ttk.LabelFrame(body, text="Command Output", padding=8)
        output_panel.grid(row=1, column=0, sticky="nsew")
        output_panel.columnconfigure(0, weight=1)
        output_panel.rowconfigure(0, weight=1)
        self.output_text = tk.Text(
            output_panel,
            wrap=tk.WORD,
            background=PALETTE.field,
            foreground=PALETTE.text,
            insertbackground=PALETTE.accent_hot,
            selectbackground=PALETTE.selection,
            selectforeground=PALETTE.text,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=PALETTE.border,
            highlightcolor=PALETTE.accent,
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(output_panel, orient=tk.VERTICAL, command=self.output_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=scrollbar.set)
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(body, textvariable=self.status_var, style="Subheader.TLabel").grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )
        self._load_tool(first)

    def _path_row(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        variable: tk.StringVar,
        callback: Callable[[], None],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
        ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(10, 8), pady=4
        )
        ttk.Button(parent, text="Browse", command=callback).grid(
            row=row, column=2, pady=4
        )

    def _selected_tool(self) -> ToolDefinition:
        return self.tools_by_name[self.tool_type_var.get()]

    def _selected_operation(self) -> ToolOperation:
        tool = self._selected_tool()
        return next(item for item in tool.operations if item.label == self.operation_var.get())

    def _tool_changed(self, _event: tk.Event[Any] | None = None) -> None:
        self._load_tool(self._selected_tool())

    def _load_tool(self, tool: ToolDefinition) -> None:
        path = self.catalog.discover(tool.id)
        self.executable_var.set(str(path or ""))
        self.credit_var.set(f"{tool.name} by {tool.author}")
        self.source_button.configure(state=tk.NORMAL if tool.homepage else tk.DISABLED)
        labels = tuple(operation.label for operation in tool.operations)
        self.operation_box.configure(values=labels)
        self.operation_var.set(labels[0])
        self.input_var.set("")
        self.output_var.set("")
        self._operation_changed()
        if path:
            digest = self.catalog.checksum(path)
            self.status_var.set(f"Detected {path.name} | SHA-256 {digest[:16]}...")
        elif not tool.supports_current_platform():
            self.status_var.set(f"{tool.name} is not native to this operating system")
        else:
            self.status_var.set(f"Choose your {tool.name} executable")
        self.run_button.configure(
            state=tk.NORMAL if tool.supports_current_platform() else tk.DISABLED
        )

    def _open_source(self) -> None:
        homepage = self._selected_tool().homepage
        if homepage:
            webbrowser.open(homepage)

    def _operation_changed(self, _event: tk.Event[Any] | None = None) -> None:
        operation = self._selected_operation()
        self.arguments_var.set(format_command(operation.arguments))
        self.risk_var.set("MODIFIES INPUT" if operation.destructive else "READ/CREATE")
        self.run_button.configure(text="Launch Tool" if operation.detached else "Run Tool")
        self.arguments_entry.configure(
            state=tk.NORMAL if operation.id == "custom" else tk.DISABLED
        )
        self._set_path_state(
            self.input_label,
            self.input_entry,
            self.input_button,
            operation.input_kind,
            "Input",
        )
        self._set_path_state(
            self.output_label,
            self.output_entry,
            self.output_button,
            operation.output_kind,
            "Output",
        )

    @staticmethod
    def _set_path_state(
        label: ttk.Label,
        entry: ttk.Entry,
        button: ttk.Button,
        kind: str,
        prefix: str,
    ) -> None:
        label.configure(
            text=(
                f"{prefix} {kind}"
                if kind not in {"none", "optional"}
                else f"{prefix} path"
            )
        )
        state = tk.DISABLED if kind == "none" else tk.NORMAL
        entry.configure(state=state)
        button.configure(state=state)

    def _choose_executable(self) -> None:
        selected = filedialog.askopenfilename(parent=self.root, title="Choose tool executable")
        if selected:
            path = self.catalog.save_path(self._selected_tool().id, selected)
            self.executable_var.set(str(path))
            self.status_var.set(f"Saved {path.name} | SHA-256 {self.catalog.checksum(path)[:16]}...")

    def _detect_executable(self) -> None:
        path = self.catalog.discover(self._selected_tool().id)
        if path:
            self.executable_var.set(str(path))
            self.status_var.set(f"Detected {path}")
        else:
            messagebox.showinfo("Tool not detected", "Choose the executable manually.", parent=self.root)

    def _choose_input(self) -> None:
        kind = self._selected_operation().input_kind
        if kind == "directory":
            selected = filedialog.askdirectory(parent=self.root, title="Choose input folder")
        elif kind == "any" and messagebox.askyesno(
            "Choose input", "Select a folder instead of a file?", parent=self.root
        ):
            selected = filedialog.askdirectory(parent=self.root, title="Choose game folder")
        else:
            selected = filedialog.askopenfilename(parent=self.root, title="Choose input file")
        if selected:
            self.input_var.set(selected)

    def _choose_output(self) -> None:
        if self._selected_operation().output_kind == "directory":
            selected = filedialog.askdirectory(parent=self.root, title="Choose output folder")
        else:
            selected = filedialog.asksaveasfilename(parent=self.root, title="Choose output file")
        if selected:
            self.output_var.set(selected)

    def run(self) -> None:
        if self.running:
            messagebox.showinfo("Tool Center", "Another tool is still running.", parent=self.root)
            return
        tool = self._selected_tool()
        operation = self._selected_operation()
        if operation.destructive and not messagebox.askyesno(
            "Confirm modifying operation",
            "This operation can modify the selected input. Continue?",
            parent=self.root,
        ):
            return
        try:
            arguments = (
                split_arguments(self.arguments_var.get())
                if self.arguments_var.get().strip()
                else []
            )
            command = self.runner.build_command(
                self.executable_var.get(),
                arguments,
                input_path=self.input_var.get(),
                output_path=self.output_var.get(),
                input_kind=operation.input_kind,
                output_kind=operation.output_kind,
            )
        except (ExternalToolError, ValueError) as exc:
            messagebox.showerror("Cannot run tool", str(exc), parent=self.root)
            return
        self.catalog.save_path(tool.id, self.executable_var.get())
        self.running = True
        self.status_var.set(f"{tool.name} is starting...")
        self._append(f"$ {format_command(command)}\n\n")

        def worker() -> None:
            try:
                if operation.detached:
                    result: ToolLaunch | ToolResult = self.runner.launch_detached(
                        self.executable_var.get(), arguments,
                        input_path=self.input_var.get(), output_path=self.output_var.get(),
                        input_kind=operation.input_kind, output_kind=operation.output_kind,
                    )
                else:
                    result = self.runner.run(
                        self.executable_var.get(), arguments,
                        input_path=self.input_var.get(), output_path=self.output_var.get(),
                        timeout=self.timeout_var.get(), input_kind=operation.input_kind,
                        output_kind=operation.output_kind,
                    )
                self.events.put(("completed", result))
            except Exception as exc:
                self.events.put(("failed", str(exc)))

        threading.Thread(target=worker, name="external-tool", daemon=True).start()
        self.root.after(100, self._poll)

    def cancel(self) -> None:
        if self.runner.cancel():
            self.status_var.set("Stopping external tool...")

    def clear_output(self) -> None:
        self.output_text.delete("1.0", tk.END)

    def _poll(self) -> None:
        while True:
            try:
                event, value = self.events.get_nowait()
            except queue.Empty:
                break
            self.running = False
            if event == "completed":
                self._show_result(value)
            else:
                self.status_var.set("External tool failed")
                self._append(f"ERROR: {value}\n")
        if self.running:
            self.root.after(100, self._poll)

    def _show_result(self, result: ToolResult | ToolLaunch) -> None:
        if isinstance(result, ToolLaunch):
            self.status_var.set(f"Tool launched with process ID {result.pid}")
            self._append(f"[Launched process {result.pid}]\n")
            return
        if result.stdout:
            self._append(result.stdout.rstrip() + "\n")
        if result.stderr:
            self._append("\nSTDERR:\n" + result.stderr.rstrip() + "\n")
        state = "cancelled" if result.cancelled else f"exit code {result.returncode}"
        self.status_var.set(f"Tool finished with {state} in {result.duration_seconds:.2f} seconds")
        self._append(f"\n[Finished: {state}; {result.duration_seconds:.2f} seconds]\n")

    def _append(self, value: str) -> None:
        if self.output_text.winfo_exists():
            self.output_text.insert(tk.END, value)
            self.output_text.see(tk.END)

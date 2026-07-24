"""Dark desktop workspace for user-supplied Xbox command-line tools."""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from external_tools import (
    ExternalToolError,
    ExternalToolRunner,
    ToolResult,
    format_command,
    split_arguments,
)


XEXTOOL_PRESETS = {
    "Extended information": '-l "{input}"',
    "Basic information": '"{input}"',
    "Custom arguments": "",
}


class ExternalToolsPage:
    """Build and coordinate the external tools workspace."""

    def __init__(
        self,
        root: tk.Tk,
        parent: ttk.Frame,
        page_header: Callable[[str, str], None],
        config_path: Path,
    ) -> None:
        self.root = root
        self.parent = parent
        self.config_path = config_path
        self.runner = ExternalToolRunner()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.running = False

        page_header(
            "External Tools",
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

        self.config = self._read_config()
        tool_config = self.config.get("external_tools", {})
        if not isinstance(tool_config, dict):
            tool_config = {}
        self.tool_type_var = tk.StringVar(value="XeXTool")
        self.executable_var = tk.StringVar(
            value=str(tool_config.get("xextool_path", ""))
        )
        self.operation_var = tk.StringVar(value="Extended information")
        self.arguments_var = tk.StringVar(
            value=XEXTOOL_PRESETS["Extended information"]
        )
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.timeout_var = tk.IntVar(value=300)

        ttk.Label(setup, text="Tool preset").grid(row=0, column=0, sticky=tk.W, pady=4)
        tool_type = ttk.Combobox(
            setup,
            textvariable=self.tool_type_var,
            values=("XeXTool", "Custom CLI tool"),
            state="readonly",
            width=24,
        )
        tool_type.grid(row=0, column=1, sticky=tk.W, padx=(10, 0), pady=4)
        tool_type.bind("<<ComboboxSelected>>", self._tool_type_changed)

        self._path_row(
            setup,
            1,
            "Executable",
            self.executable_var,
            self._choose_executable,
        )

        ttk.Label(setup, text="Operation").grid(row=2, column=0, sticky=tk.W, pady=4)
        self.operation_box = ttk.Combobox(
            setup,
            textvariable=self.operation_var,
            values=tuple(XEXTOOL_PRESETS),
            state="readonly",
            width=24,
        )
        self.operation_box.grid(row=2, column=1, sticky=tk.W, padx=(10, 0), pady=4)
        self.operation_box.bind("<<ComboboxSelected>>", self._operation_changed)

        self._path_row(setup, 3, "Input file", self.input_var, self._choose_input)
        self._path_row(setup, 4, "Output path", self.output_var, self._choose_output)

        ttk.Label(setup, text="Arguments").grid(row=5, column=0, sticky=tk.W, pady=4)
        self.arguments_entry = ttk.Entry(setup, textvariable=self.arguments_var)
        self.arguments_entry.grid(
            row=5, column=1, columnspan=2, sticky="ew", padx=(10, 0), pady=4
        )

        ttk.Label(setup, text="Timeout seconds").grid(
            row=6, column=0, sticky=tk.W, pady=4
        )
        ttk.Spinbox(
            setup,
            from_=1,
            to=3600,
            textvariable=self.timeout_var,
            width=10,
        ).grid(row=6, column=1, sticky=tk.W, padx=(10, 0), pady=4)

        controls = ttk.Frame(setup)
        controls.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(
            controls,
            text="Run Tool",
            command=self.run,
            style="Accent.TButton",
        ).pack(side=tk.LEFT)
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
            background="#070b08",
            foreground="#f2f5f2",
            insertbackground="#72e000",
            selectbackground="#315f12",
            selectforeground="#f2f5f2",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#26352a",
            highlightcolor="#72e000",
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(
            output_panel,
            orient=tk.VERTICAL,
            command=self.output_text.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=scrollbar.set)

        self.status_var = tk.StringVar(
            value="Choose a trusted executable and an input file."
        )
        ttk.Label(body, textvariable=self.status_var, style="Subheader.TLabel").grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

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

    def _tool_type_changed(self, _event: tk.Event[Any]) -> None:
        custom = self.tool_type_var.get() == "Custom CLI tool"
        tool_config = self._read_config().get("external_tools", {})
        if not isinstance(tool_config, dict):
            tool_config = {}
        path_key = "custom_tool_path" if custom else "xextool_path"
        self.executable_var.set(str(tool_config.get(path_key, "")))
        self.operation_var.set("Custom arguments" if custom else "Extended information")
        self.arguments_var.set("" if custom else XEXTOOL_PRESETS["Extended information"])
        self.operation_box.configure(state=tk.DISABLED if custom else "readonly")

    def _operation_changed(self, _event: tk.Event[Any]) -> None:
        operation = self.operation_var.get()
        self.arguments_var.set(XEXTOOL_PRESETS.get(operation, ""))
        self.arguments_entry.focus_set()

    def _choose_executable(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose command-line tool",
        )
        if selected:
            self.executable_var.set(selected)
            self._save_tool_path()

    def _choose_input(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose tool input",
            filetypes=(
                ("Xbox executable", "*.xex"),
                ("All files", "*.*"),
            ),
        )
        if selected:
            self.input_var.set(selected)

    def _choose_output(self) -> None:
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Choose optional output path",
        )
        if selected:
            self.output_var.set(selected)

    def run(self) -> None:
        if self.running:
            messagebox.showinfo(
                "External Tools",
                "Another tool is still running.",
                parent=self.root,
            )
            return
        try:
            arguments = split_arguments(self.arguments_var.get())
            command = self.runner.build_command(
                self.executable_var.get(),
                arguments,
                input_path=self.input_var.get(),
                output_path=self.output_var.get(),
            )
        except (ExternalToolError, ValueError) as exc:
            messagebox.showerror("Cannot run tool", str(exc), parent=self.root)
            return

        self._save_tool_path()
        self.running = True
        self.status_var.set("External tool is running...")
        self._append(f"$ {format_command(command)}\n\n")

        def worker() -> None:
            try:
                result = self.runner.run(
                    self.executable_var.get(),
                    arguments,
                    input_path=self.input_var.get(),
                    output_path=self.output_var.get(),
                    timeout=self.timeout_var.get(),
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

    def _show_result(self, result: ToolResult) -> None:
        if result.stdout:
            self._append(result.stdout.rstrip() + "\n")
        if result.stderr:
            self._append("\nSTDERR:\n" + result.stderr.rstrip() + "\n")
        state = "cancelled" if result.cancelled else f"exit code {result.returncode}"
        self.status_var.set(
            f"Tool finished with {state} in {result.duration_seconds:.2f} seconds"
        )
        self._append(
            f"\n[Finished: {state}; {result.duration_seconds:.2f} seconds]\n"
        )

    def _append(self, value: str) -> None:
        if self.output_text.winfo_exists():
            self.output_text.insert(tk.END, value)
            self.output_text.see(tk.END)

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_tool_path(self) -> None:
        if not self.executable_var.get().strip():
            return
        config = self._read_config()
        tools = config.setdefault("external_tools", {})
        if not isinstance(tools, dict):
            tools = {}
            config["external_tools"] = tools
        path_key = (
            "custom_tool_path"
            if self.tool_type_var.get() == "Custom CLI tool"
            else "xextool_path"
        )
        tools[path_key] = self.executable_var.get()
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

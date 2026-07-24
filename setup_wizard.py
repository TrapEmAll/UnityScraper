"""First-run setup wizard for UnityScraper."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_paths import (
    CONFIG_PATH,
    DOWNLOADS_DIR,
    FIRST_RUN_PATH,
    TITLEIDS_PATH,
    ensure_app_dirs,
    ensure_user_titleids_file,
)
from platform_support import desktop_font_family


UI_FONT = desktop_font_family()


class SetupWizard(tk.Toplevel):
    """Small first-run wizard that records safe defaults."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.parent = parent
        self.completed = False
        self.title("Welcome to UnityScraper")
        self.geometry("620x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        ensure_app_dirs()
        ensure_user_titleids_file()

        self.output_var = tk.StringVar(value=str(DOWNLOADS_DIR))
        self.titleids_var = tk.StringVar()
        self.collection_var = tk.StringVar()

        self._build()

    def _build(self) -> None:
        container = ttk.Frame(self, padding=24)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            container,
            text="Set up your Xbox 360 archive",
            font=(UI_FONT, 18, "bold"),
        ).pack(anchor=tk.W)

        ttk.Label(
            container,
            text=(
                "UnityScraper scans XboxUnity metadata first, then lets you "
                "choose which covers and compatible title updates to download."
            ),
            wraplength=560,
        ).pack(anchor=tk.W, pady=(8, 22))

        ttk.Label(container, text="Archive folder").pack(anchor=tk.W)
        folder_row = ttk.Frame(container)
        folder_row.pack(fill=tk.X, pady=(5, 16))

        ttk.Entry(folder_row, textvariable=self.output_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(folder_row, text="Browse…", command=self._browse).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        ttk.Label(container, text="Optional TitleIDs").pack(anchor=tk.W)
        ttk.Entry(container, textvariable=self.titleids_var).pack(
            fill=tk.X, pady=(5, 4)
        )
        ttk.Label(
            container,
            text="Comma-separated, for example: 4D53082D, 584109A8",
        ).pack(anchor=tk.W)

        ttk.Label(container, text="Optional collection folder").pack(anchor=tk.W, pady=(16, 0))
        collection_row = ttk.Frame(container)
        collection_row.pack(fill=tk.X, pady=(5, 4))
        ttk.Entry(collection_row, textvariable=self.collection_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        ttk.Button(collection_row, text="Browse", command=self._browse_collection).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        ttk.Separator(container).pack(fill=tk.X, pady=22)

        ttk.Label(
            container,
            text=(
                "Recommended defaults will be used for request rate, retries, "
                "worker count, and timeouts. These can be changed later under Settings."
            ),
            wraplength=560,
        ).pack(anchor=tk.W)

        buttons = ttk.Frame(container)
        buttons.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(
            buttons,
            text="Finish Setup",
            command=self._finish,
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def _browse(self) -> None:
        selected = filedialog.askdirectory(
            parent=self,
            initialdir=self.output_var.get(),
            title="Choose archive folder",
        )
        if selected:
            self.output_var.set(selected)

    def _browse_collection(self) -> None:
        selected = filedialog.askdirectory(parent=self, title="Choose Xbox 360 collection")
        if selected:
            self.collection_var.set(selected)

    def _finish(self) -> None:
        output = Path(self.output_var.get()).expanduser()
        try:
            output.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror(
                "Unable to use folder",
                f"UnityScraper could not create or use that folder:\n\n{exc}",
                parent=self,
            )
            return

        config: dict[str, object] = {}
        if CONFIG_PATH.exists():
            try:
                config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                config = {}

        config.update(
            {
                "output_dir": str(output),
                "workers": int(config.get("workers", 4)),
                "rate_limit": float(config.get("rate_limit", 0.35)),
                "timeout": int(config.get("timeout", 30)),
                "max_retries": int(config.get("max_retries", 3)),
                "collection_roots": (
                    [self.collection_var.get().strip()]
                    if self.collection_var.get().strip()
                    else config.get("collection_roots", [])
                ),
                "ui_scale": float(config.get("ui_scale", 1.0)),
            }
        )
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")

        titleids = [
            value.strip().upper()
            for value in self.titleids_var.get().replace("\n", ",").split(",")
            if value.strip()
        ]
        if titleids:
            TITLEIDS_PATH.write_text(",".join(dict.fromkeys(titleids)), encoding="utf-8")

        FIRST_RUN_PATH.write_text("complete\n", encoding="utf-8")
        self.completed = True
        self.destroy()


def run_first_run_wizard(parent: tk.Misc) -> bool:
    """Run the wizard when setup has not yet been completed."""
    if FIRST_RUN_PATH.exists():
        return True

    wizard = SetupWizard(parent)
    parent.wait_window(wizard)
    return wizard.completed

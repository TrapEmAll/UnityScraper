import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from downloader import UnityScraper


class App(tk.Tk):
    """
    Tkinter GUI for UnityScraper.

    Fixes/improvements:
      - Configurable output directory
      - TitleID validation/normalization
      - Keeps UI updates thread-safe via a queue + after()
    """

    def __init__(self):
        super().__init__()

        self.title("UnityScraper GUI")
        self.geometry("760x520")

        self._queue = queue.Queue()
        self._worker_thread = None

        # Defaults
        self.output_dir = tk.StringVar(value="unityscrape")
        self.rate_limit = tk.DoubleVar(value=0.35)
        self.workers = tk.IntVar(value=UnityScraper.DEFAULT_MAX_WORKERS)

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        # TitleIDs input
        ttk.Label(frm, text="TitleIDs (comma separated):").grid(row=0, column=0, sticky="w", **pad)
        self.entry_ids = ttk.Entry(frm, width=70)
        self.entry_ids.grid(row=1, column=0, columnspan=3, sticky="we", **pad)

        # Output directory selector
        ttk.Label(frm, text="Output folder:").grid(row=2, column=0, sticky="w", **pad)
        self.entry_out = ttk.Entry(frm, textvariable=self.output_dir, width=55)
        self.entry_out.grid(row=3, column=0, columnspan=2, sticky="we", **pad)
        ttk.Button(frm, text="Browse...", command=self._browse_out).grid(row=3, column=2, sticky="e", **pad)

        # Workers + Rate limit
        ttk.Label(frm, text="Workers:").grid(row=4, column=0, sticky="w", **pad)
        self.spin_workers = ttk.Spinbox(frm, from_=1, to=16, textvariable=self.workers, width=6)
        self.spin_workers.grid(row=4, column=0, sticky="w", padx=80, pady=6)

        ttk.Label(frm, text="Min seconds/request:").grid(row=4, column=1, sticky="w", **pad)
        self.entry_rate = ttk.Entry(frm, textvariable=self.rate_limit, width=8)
        self.entry_rate.grid(row=4, column=1, sticky="w", padx=160, pady=6)

        # Buttons
        self.btn_start = ttk.Button(frm, text="Start", command=self.start)
        self.btn_start.grid(row=5, column=0, sticky="w", **pad)

        self.btn_stop = ttk.Button(frm, text="Stop (best-effort)", command=self.stop, state="disabled")
        self.btn_stop.grid(row=5, column=1, sticky="w", **pad)

        # Progress bar
        self.progress = ttk.Progressbar(frm, orient="horizontal", mode="determinate", length=600)
        self.progress.grid(row=6, column=0, columnspan=3, sticky="we", **pad)

        self.lbl_status = ttk.Label(frm, text="Idle.")
        self.lbl_status.grid(row=7, column=0, columnspan=3, sticky="w", **pad)

        # History / log
        ttk.Label(frm, text="History:").grid(row=8, column=0, sticky="w", **pad)
        self.listbox = tk.Listbox(frm, height=12)
        self.listbox.grid(row=9, column=0, columnspan=3, sticky="nsew", **pad)

        frm.grid_columnconfigure(0, weight=1)
        frm.grid_columnconfigure(1, weight=1)
        frm.grid_columnconfigure(2, weight=0)
        frm.grid_rowconfigure(9, weight=1)

    def _browse_out(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_dir.set(folder)

    def _parse_title_ids(self):
        raw = self.entry_ids.get().strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]

        valid = []
        invalid = []
        for p in parts:
            tid = UnityScraper.normalize_title_id(p)
            if tid:
                valid.append(tid)
            else:
                invalid.append(p)

        return valid, invalid

    def start(self):
        if self._worker_thread and self._worker_thread.is_alive():
            messagebox.showinfo("Busy", "A run is already in progress.")
            return

        title_ids, invalid = self._parse_title_ids()
        if not title_ids:
            messagebox.showerror("No TitleIDs", "Please enter at least one valid 8-hex TitleID.")
            return

        if invalid:
            messagebox.showwarning("Invalid TitleIDs", "Skipping invalid TitleIDs:\n" + "\n".join(invalid))

        # UI state
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.configure(maximum=len(title_ids), value=0)
        self.listbox.insert(tk.END, f"Starting run: {len(title_ids)} TitleID(s)")
        self.lbl_status.configure(text="Running...")

        out_dir = self.output_dir.get().strip() or "unityscrape"

        # Validate numeric fields safely
        try:
            workers = int(self.workers.get())
            rate = float(self.rate_limit.get())
        except Exception:
            messagebox.showerror("Invalid settings", "Workers must be an int and min seconds/request must be a number.")
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            return

        self._stop_flag = threading.Event()
        self._worker_thread = threading.Thread(
            target=self._run_job,
            args=(title_ids, out_dir, workers, rate),
            daemon=True,
        )
        self._worker_thread.start()

    def stop(self):
        # Best-effort stop: we mark a flag; ongoing network calls will finish.
        if hasattr(self, "_stop_flag"):
            self._stop_flag.set()
        self.listbox.insert(tk.END, "Stop requested (best-effort).")

    def _run_job(self, title_ids, out_dir, workers, rate):
        """
        Background worker thread. Reports UI updates via queue.
        """
        scraper = UnityScraper(
            base_dir=out_dir,
            max_workers=max(1, workers),
            min_request_interval=max(0.0, rate),
        )

        failed = []
        for idx, tid in enumerate(title_ids, start=1):
            if self._stop_flag.is_set():
                self._queue.put(("status", "Stopped by user."))
                break

            self._queue.put(("status", f"Processing {tid} ({idx}/{len(title_ids)})..."))
            self._queue.put(("log", f"=== {tid} ==="))

            ok1 = scraper.download_covers(tid)
            ok2 = scraper.download_updates(tid)

            if not (ok1 and ok2):
                failed.append(tid)
                self._queue.put(("log", f"{tid}: issues (covers={ok1}, updates={ok2})"))
            else:
                self._queue.put(("log", f"{tid}: OK"))

            self._queue.put(("progress", idx))

        if failed:
            self._queue.put(("done", f"Finished with failures: {', '.join(failed)}"))
        else:
            self._queue.put(("done", "Finished successfully."))

    def _poll_queue(self):
        """
        Main-thread polling loop to apply UI updates safely.
        """
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]

                if kind == "status":
                    self.lbl_status.configure(text=msg[1])

                elif kind == "log":
                    self.listbox.insert(tk.END, msg[1])
                    self.listbox.yview_moveto(1)

                elif kind == "progress":
                    self.progress.configure(value=msg[1])

                elif kind == "done":
                    self.lbl_status.configure(text=msg[1])
                    self.listbox.insert(tk.END, msg[1])
                    self.listbox.yview_moveto(1)
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")

        except queue.Empty:
            pass

        self.after(100, self._poll_queue)


if __name__ == "__main__":
    App().mainloop()

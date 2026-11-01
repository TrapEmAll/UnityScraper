"""Command palette: a keyboard-first quick-open overlay for pages, actions and games."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Sequence

from ui_theme import PALETTE, font, text_options

VISIBLE_ROWS = 9
_DEBOUNCE_MS = 60
_SEPARATORS = " -_./\\:()[]&+,"
_WORD_START = 2.0
_PREFIX = 2.0
_CONTIGUOUS = 1.5
_SECONDARY_WEIGHT = 0.5


@dataclass(frozen=True)
class PaletteEntry:
    """One runnable palette item; ``kind`` is a short badge such as Page, Action or Game."""

    title: str
    kind: str
    action: Callable[[], None]
    subtitle: str = ""
    keywords: str = ""
    shortcut: str = ""


def fuzzy_score(query: str, text: str) -> float | None:
    """Score ``query`` as a case-insensitive subsequence of ``text``; ``None`` when it is not one.

    Whitespace in the query is ignored. Contiguous runs, word starts, a match at the very start
    and shorter texts score higher. Always ``>= 0`` so callers can discount it safely.
    """
    needle = "".join(query.lower().split())
    if not needle:
        return 0.0
    haystack = text.lower()
    size = len(haystack)
    if len(needle) > size:
        return None
    starts = [
        j == 0 or text[j - 1] in _SEPARATORS or (text[j].isupper() and text[j - 1].islower())
        for j in range(size)
    ]
    # row[j]: best score with the current query char matched at text position j.
    row: list[float | None] = []
    for i, char in enumerate(needle):
        current: list[float | None] = [None] * size
        best_gap: float | None = None  # best previous-row score at any k < j - 1
        for j in range(size):
            if i and j >= 2 and row[j - 2] is not None:
                best_gap = row[j - 2] if best_gap is None else max(best_gap, row[j - 2])
            if haystack[j] != char:
                continue
            gain = 1.0 + (_WORD_START if starts[j] else 0.0)
            if i == 0:
                current[j] = gain + (_PREFIX if j == 0 else 0.0)
                continue
            options = [best_gap] if best_gap is not None else []
            if j and row[j - 1] is not None:
                options.append(row[j - 1] + _CONTIGUOUS)
            if options:
                current[j] = gain + max(options)
        row = current
    best = max((score for score in row if score is not None), default=None)
    return None if best is None else best / (1 + size / 200)


def rank(query: str, entries: Sequence[PaletteEntry], limit: int = 50) -> list[PaletteEntry]:
    """Best matches first; title beats subtitle/keywords. Empty query keeps the given order."""
    if not query.strip():
        return list(entries[:limit])
    scored: list[tuple[float, PaletteEntry]] = []
    for entry in entries:
        scores = [fuzzy_score(query, entry.title)]
        scores += [
            None if score is None else score * _SECONDARY_WEIGHT
            for score in (fuzzy_score(query, entry.subtitle), fuzzy_score(query, entry.keywords))
        ]
        best = max((score for score in scores if score is not None), default=None)
        if best is not None:
            scored.append((best, entry))
    scored.sort(key=lambda item: -item[0])  # stable: ties keep input order
    return [entry for _, entry in scored[:limit]]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class CommandPalette:
    """Borderless overlay near the top of ``root``: type to filter, arrows to move, Enter to run.

    Constructing it opens it; ``entries()`` is called once. Opening a second palette closes the
    first.
    """

    _active: CommandPalette | None = None

    def __init__(
        self,
        root: tk.Tk,
        entries: Callable[[], Sequence[PaletteEntry]],
        placeholder: str = "Type a command, page, or game…",
    ) -> None:
        if CommandPalette._active is not None:
            CommandPalette._active.close()
        CommandPalette._active = self
        self.root = root
        self._closed = False
        self._focused = False
        self._refresh_job: str | None = None
        self._results: list[PaletteEntry] = []
        self._selected = 0
        self._offset = 0
        try:
            self._previous_focus = root.focus_get()
        except (KeyError, tk.TclError):
            self._previous_focus = None

        self.window = tk.Toplevel(root, background=PALETTE.border)
        self.window.withdraw()
        self.window.overrideredirect(True)
        body = tk.Frame(self.window, background=PALETTE.panel_alt, padx=12, pady=12)
        body.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        body.columnconfigure(0, weight=1)

        self.query = tk.StringVar(master=self.window)
        options = {**text_options(), "font": font("medium")}
        self.entry = tk.Entry(body, textvariable=self.query, **options)
        self.entry.grid(row=0, column=0, sticky="ew", ipady=6)
        self._placeholder = tk.Label(
            self.entry,
            text=placeholder,
            background=PALETTE.field,
            foreground=PALETTE.muted,
            font=font("medium"),
        )
        self._placeholder.place(x=2, rely=0.5, anchor="w")
        tk.Frame(body, height=1, background=PALETTE.border).grid(
            row=1, column=0, sticky="ew", pady=(10, 6)
        )
        rows = tk.Frame(body, background=PALETTE.panel_alt)
        rows.grid(row=2, column=0, sticky="nsew")
        rows.columnconfigure(0, weight=1)
        self._rows = [self._build_row(rows, slot) for slot in range(VISIBLE_ROWS)]
        self._empty = tk.Label(
            rows,
            text="No matches",
            background=PALETTE.panel_alt,
            foreground=PALETTE.muted,
            font=font(),
            pady=12,
        )
        tk.Label(
            body,
            text="↑↓ Move   Enter Run   Esc Close",
            background=PALETTE.panel_alt,
            foreground=PALETTE.muted,
            font=font("small"),
            anchor="e",
        ).grid(row=3, column=0, sticky="ew", pady=(6, 0))

        self.query.trace_add("write", self._schedule_refresh)
        for sequence, delta in (
            ("<Up>", -1), ("<Down>", 1), ("<Prior>", -VISIBLE_ROWS), ("<Next>", VISIBLE_ROWS)
        ):
            self.entry.bind(sequence, lambda _event, d=delta: self._move(d))
        self.entry.bind("<Return>", lambda _event: self._run(None))
        self.entry.bind("<KP_Enter>", lambda _event: self._run(None))
        self.entry.bind("<Escape>", lambda _event: self._close_event())
        self.window.bind("<Button-1>", self._on_click)
        self.window.bind("<MouseWheel>", lambda event: self._move(-1 if event.delta > 0 else 1))
        self.window.bind("<Button-4>", lambda _event: self._move(-1))
        self.window.bind("<Button-5>", lambda _event: self._move(1))
        self.window.bind("<FocusIn>", self._on_focus_in)
        self.window.bind("<FocusOut>", self._on_focus_out)

        self._entries = list(entries())
        self._refresh()
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self.entry.focus_set()
        self._grab()

    def close(self) -> None:
        """Destroy the palette, release the grab and give focus back to where it was."""
        if self._closed:
            return
        self._closed = True
        if CommandPalette._active is self:
            CommandPalette._active = None
        if self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
            self._refresh_job = None
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        self.window.destroy()
        if self._previous_focus is not None:
            try:
                self._previous_focus.focus_set()
            except tk.TclError:
                pass

    def _build_row(
        self, parent: tk.Frame, slot: int
    ) -> tuple[tk.Frame, tk.Label, tk.Label, tk.Label, tk.Label]:
        frame = tk.Frame(parent, padx=10, pady=6, cursor="hand2")
        frame.columnconfigure(1, weight=1)
        title = tk.Label(frame, font=font(), anchor="w")
        subtitle = tk.Label(frame, font=font("small"), anchor="w")
        shortcut = tk.Label(frame, font=font("small"))
        badge = tk.Label(frame, font=font("small"), padx=6)
        title.grid(row=0, column=0, sticky="w")
        subtitle.grid(row=0, column=1, sticky="ew", padx=8)
        shortcut.grid(row=0, column=2, padx=(0, 8))
        badge.grid(row=0, column=3)
        for widget in (frame, title, subtitle, shortcut, badge):
            widget.bind("<Button-1>", lambda _event, s=slot: self._run(self._offset + s))
        return frame, title, subtitle, shortcut, badge

    def _schedule_refresh(self, *_args: object) -> None:
        if self.query.get():
            self._placeholder.place_forget()
        else:
            self._placeholder.place(x=2, rely=0.5, anchor="w")
        if self._refresh_job is not None:
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(_DEBOUNCE_MS, self._refresh)

    def _refresh(self) -> None:
        self._refresh_job = None
        if self._closed:
            return
        self._results = rank(self.query.get(), self._entries)
        self._selected = self._offset = 0
        self._paint()
        if self._results:
            self._empty.grid_remove()
        else:
            self._empty.grid(row=VISIBLE_ROWS, column=0, sticky="ew")
        self._place()

    def _paint(self) -> None:
        visible = self._results[self._offset:self._offset + VISIBLE_ROWS]
        for slot, (frame, title, subtitle, shortcut, badge) in enumerate(self._rows):
            if slot >= len(visible):
                frame.grid_remove()
                continue
            entry = visible[slot]
            selected = self._offset + slot == self._selected
            background = PALETTE.selection if selected else PALETTE.panel_alt
            foreground = PALETTE.selection_text if selected else PALETTE.text
            secondary = foreground if selected else PALETTE.muted
            frame.configure(background=background)
            title.configure(
                text=_clip(entry.title, 72), background=background, foreground=foreground
            )
            subtitle.configure(text=entry.subtitle, background=background, foreground=secondary)
            shortcut.configure(text=entry.shortcut, background=background, foreground=secondary)
            badge.configure(text=entry.kind, background=PALETTE.hover, foreground=PALETTE.muted)
            frame.grid(row=slot, column=0, sticky="ew")

    def _place(self) -> None:
        root = self.root
        self.window.update_idletasks()
        width = max(360, min(640, root.winfo_width() - 48))
        height = self.window.winfo_reqheight()
        x = root.winfo_rootx() + (root.winfo_width() - width) // 2
        y = root.winfo_rooty() + root.winfo_height() // 5
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _move(self, delta: int) -> str:
        if self._results:
            self._selected = max(0, min(len(self._results) - 1, self._selected + delta))
            if self._selected < self._offset:
                self._offset = self._selected
            elif self._selected >= self._offset + VISIBLE_ROWS:
                self._offset = self._selected - VISIBLE_ROWS + 1
            self._paint()
        return "break"

    def _run(self, index: int | None) -> str:
        """Run row ``index`` (a click) or, for ``None`` (Enter), the selection for the query."""
        if index is None:
            if self._refresh_job is not None:  # typed faster than the debounce
                self.root.after_cancel(self._refresh_job)
                self._refresh()
            index = self._selected
        if 0 <= index < len(self._results):
            entry = self._results[index]
            self.close()
            entry.action()
        return "break"

    def _close_event(self) -> str:
        self.close()
        return "break"

    def _on_click(self, event: tk.Event) -> None:
        # With the grab held, clicks anywhere in the app are delivered here.
        left, top = self.window.winfo_rootx(), self.window.winfo_rooty()
        inside_x = left <= event.x_root < left + self.window.winfo_width()
        inside_y = top <= event.y_root < top + self.window.winfo_height()
        if not (inside_x and inside_y):
            self.close()

    def _on_focus_in(self, _event: tk.Event) -> None:
        self._focused = True

    def _on_focus_out(self, _event: tk.Event) -> None:
        # Only after focus actually arrived: borderless windows can get FocusOut while opening.
        if self._focused and not self._closed:
            self.root.after(50, self._close_if_unfocused)

    def _close_if_unfocused(self) -> None:
        if self._closed:
            return
        try:
            focused = self.window.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if focused is None or str(focused.winfo_toplevel()) != str(self.window):
            self.close()

    def _grab(self, attempts: int = 10) -> None:
        if self._closed:
            return
        try:
            self.window.grab_set()
        except tk.TclError:  # not viewable yet
            if attempts:
                self.root.after(30, self._grab, attempts - 1)

"""Dialog for adding a flag to a clip."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from src.gui.dialogs.base import ModalDialog
from src.gui.theme import Spacing
from src.models import Clip


class AddFlagDialog(ModalDialog):
    """Collect frame, note, color, and type for a new flag."""

    def __init__(
        self,
        parent,
        clip: Clip,
        max_frame: int,
        on_add: Callable[[int, str, str, str], None],
    ) -> None:
        super().__init__(parent, f"Add Flag — {clip.display_name}")
        self._on_add = on_add
        self._max_frame = max(0, max_frame)

        ttk.Label(self.body, text="Frame number", style="MutedSurface.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self._frame_var = tk.StringVar(value="0")
        ttk.Entry(self.body, textvariable=self._frame_var, width=12).grid(
            row=1, column=0, sticky="w", pady=(0, Spacing.SECTION)
        )
        if self._max_frame > 0:
            ttk.Label(
                self.body,
                text=f"Valid range: 0–{self._max_frame}",
                style="MutedSurface.TLabel",
            ).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="Note (optional)", style="MutedSurface.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        self._note_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self._note_var, width=42).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION)
        )

        ttk.Label(self.body, text="Color", style="MutedSurface.TLabel").grid(
            row=4, column=0, sticky="w", pady=(0, 4)
        )
        self._color_var = tk.StringVar(value="#3B82F6")
        ttk.Entry(self.body, textvariable=self._color_var, width=16).grid(
            row=5, column=0, sticky="w", pady=(0, Spacing.SECTION)
        )

        ttk.Label(self.body, text="Type", style="MutedSurface.TLabel").grid(
            row=6, column=0, sticky="w", pady=(0, 4)
        )
        self._type_var = tk.StringVar(value="general")
        ttk.Entry(self.body, textvariable=self._type_var, width=16).grid(
            row=7, column=0, sticky="w", pady=(0, Spacing.SECTION)
        )

        self.body.columnconfigure(0, weight=1)
        self.add_button_row(8, "Add Flag", self._submit)

        self.update_idletasks()
        self.center_over(parent)

    def _submit(self) -> None:
        raw_frame = self._frame_var.get().strip()
        if not raw_frame.lstrip("-").isdigit():
            messagebox.showwarning("Invalid frame", "Enter a whole frame number.", parent=self)
            return

        frame = int(raw_frame)
        if frame < 0:
            messagebox.showwarning("Invalid frame", "Frame must be 0 or greater.", parent=self)
            return
        if self._max_frame > 0 and frame > self._max_frame:
            messagebox.showwarning(
                "Invalid frame",
                f"Frame must be between 0 and {self._max_frame}.",
                parent=self,
            )
            return

        self._on_add(
            frame,
            self._note_var.get().strip(),
            self._color_var.get().strip() or "#3B82F6",
            self._type_var.get().strip() or "general",
        )
        self.destroy()

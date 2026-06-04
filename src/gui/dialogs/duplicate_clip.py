"""Dialog for duplicating a clip with a new display name."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from src.gui.dialogs.base import ModalDialog
from src.gui.theme import Spacing
from src.models import Clip

OnDuplicateClip = Callable[[str], None]


class DuplicateClipDialog(ModalDialog):
    """Confirm duplication and name the new workspace clip."""

    def __init__(
        self,
        parent: tk.Misc,
        source_clip: Clip,
        on_duplicate: OnDuplicateClip,
    ) -> None:
        super().__init__(parent, "Duplicate Clip")
        self._on_duplicate = on_duplicate
        self._source_clip = source_clip

        ttk.Label(
            self.body,
            text=f"Create an independent copy of “{source_clip.display_name}” "
            "with its own media files. The copy is added to the workspace.",
            style="MutedSurface.TLabel",
            wraplength=400,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, Spacing.SECTION))

        ttk.Label(self.body, text="New clip name", style="MutedSurface.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 4)
        )
        self._name_var = tk.StringVar(value=f"{source_clip.display_name} (copy)")
        name_entry = ttk.Entry(self.body, textvariable=self._name_var, width=42)
        name_entry.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION))

        self.body.columnconfigure(0, weight=1)
        self.add_button_row(3, "Duplicate", self._submit)

        self.update_idletasks()
        self.center_over(parent)
        name_entry.focus_set()
        name_entry.select_range(0, tk.END)

    def _submit(self) -> None:
        display_name = self._name_var.get().strip()
        if not display_name:
            messagebox.showwarning(
                "Name required",
                "Enter a display name for the duplicated clip.",
                parent=self,
            )
            return

        self._on_duplicate(display_name)
        self.destroy()

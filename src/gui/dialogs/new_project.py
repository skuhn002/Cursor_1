"""Dialog for creating a new project."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from src.gui.dialogs.base import ModalDialog
from src.gui.theme import Spacing


class NewProjectDialog(ModalDialog):
    """Collect a project name and save location."""

    def __init__(self, parent, on_create: Callable[[str, Path], None]) -> None:
        super().__init__(parent, "New Project")
        self._on_create = on_create

        ttk.Label(self.body, text="Project name", style="MutedSurface.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self._name_var = tk.StringVar()
        name_entry = ttk.Entry(self.body, textvariable=self._name_var, width=42)
        name_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION))
        name_entry.focus_set()

        ttk.Label(self.body, text="Save location", style="MutedSurface.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        self._location_var = tk.StringVar(value=str(Path.cwd()))
        ttk.Entry(self.body, textvariable=self._location_var, width=34).grid(
            row=3, column=0, sticky="ew", pady=(0, Spacing.SECTION)
        )
        ttk.Button(self.body, text="Browse…", command=self._browse_location).grid(
            row=3, column=1, padx=(8, 0), pady=(0, Spacing.SECTION)
        )

        self.body.columnconfigure(0, weight=1)
        self.add_button_row(4, "Create Project", self._submit)

        self.update_idletasks()
        self.center_over(parent)

    def _browse_location(self) -> None:
        directory = filedialog.askdirectory(
            parent=self,
            title="Choose project location",
            initialdir=self._location_var.get() or str(Path.cwd()),
        )
        if directory:
            self._location_var.set(directory)

    def _submit(self) -> None:
        name = self._name_var.get().strip()
        location = Path(self._location_var.get().strip() or ".").expanduser()

        if not name:
            messagebox.showwarning("Missing name", "Enter a project name.", parent=self)
            return
        if not location.is_dir():
            messagebox.showerror("Invalid location", f"Folder not found:\n{location}", parent=self)
            return

        self._on_create(name, location)
        self.destroy()

"""Dialog for importing a video file."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Optional

from src.gui.constants import VIDEO_FILETYPES
from src.gui.dialogs.base import ModalDialog
from src.gui.theme import Spacing


class ImportVideoDialog(ModalDialog):
    """Pick a video file and optional display name."""

    def __init__(self, parent, on_import: Callable[[Path, Optional[str]], None]) -> None:
        super().__init__(parent, "Import Video")
        self._on_import = on_import

        ttk.Label(self.body, text="Video file", style="MutedSurface.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        self._file_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self._file_var, width=38).grid(
            row=1, column=0, sticky="ew", pady=(0, Spacing.SECTION)
        )
        ttk.Button(self.body, text="Browse…", command=self._browse_file).grid(
            row=1, column=1, padx=(8, 0), pady=(0, Spacing.SECTION)
        )

        ttk.Label(self.body, text="Display name (optional)", style="MutedSurface.TLabel").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        self._name_var = tk.StringVar()
        ttk.Entry(self.body, textvariable=self._name_var, width=42).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, Spacing.SECTION)
        )

        self.body.columnconfigure(0, weight=1)
        self.add_button_row(4, "Import Video", self._submit)

        self.update_idletasks()
        self.center_over(parent)

    def _browse_file(self) -> None:
        file_path = self.ask_open_filename(
            title="Select video file",
            filetypes=VIDEO_FILETYPES,
        )
        if file_path:
            self._file_var.set(file_path)
            if not self._name_var.get().strip():
                self._name_var.set(Path(file_path).stem)

    def _submit(self) -> None:
        file_path = Path(self._file_var.get().strip()).expanduser()
        if not file_path.is_file():
            messagebox.showwarning("Missing file", "Choose a valid video file to import.", parent=self)
            return

        display_name = self._name_var.get().strip() or None
        self._on_import(file_path, display_name)
        self.destroy()

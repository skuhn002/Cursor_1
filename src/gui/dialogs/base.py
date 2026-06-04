"""Base class for modal dialogs."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, ttk

from src.gui.theme import Spacing


class ModalDialog(tk.Toplevel):
    """Centered modal dialog with consistent layout and keyboard shortcuts."""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.body = ttk.Frame(self, padding=Spacing.DIALOG, style="Surface.TFrame")
        self.body.grid(row=0, column=0, sticky="nsew")

        self.bind("<Escape>", lambda _event: self.destroy())

    def ask_open_filename(
        self,
        *,
        title: str,
        filetypes: list[tuple[str, str]],
    ) -> str:
        """Open a file picker; releases modal grab so the dialog works on Windows."""
        self.grab_release()
        try:
            return filedialog.askopenfilename(
                parent=self.winfo_toplevel(),
                title=title,
                filetypes=filetypes,
            )
        finally:
            if self.winfo_exists():
                self.grab_set()

    def center_over(self, parent: tk.Misc) -> None:
        """Center this dialog over the parent window."""
        self.update_idletasks()
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def add_button_row(
        self,
        row: int,
        confirm_text: str,
        on_confirm,
        *,
        accent: bool = True,
    ) -> None:
        """Add a standard Cancel / Confirm button row."""
        buttons = ttk.Frame(self.body, style="Surface.TFrame")
        buttons.grid(row=row, column=0, columnspan=2, sticky="e", pady=(Spacing.SECTION, 0))

        style = "Accent.TButton" if accent else "TButton"
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text=confirm_text, style=style, command=on_confirm).pack(side="right")

        self.bind("<Return>", lambda _event: on_confirm())

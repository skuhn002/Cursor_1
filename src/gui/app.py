"""Simple tkinter GUI for Moment project and import workflows."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from src.api.project_service import ProjectService, ProjectServiceError
from src.models import Clip
from src.project_state import load_active_project_path, save_active_project_path

VIDEO_FILETYPES = [
    ("Video files", "*.mp4 *.mov *.avi *.mkv *.webm *.m4v *.wmv"),
    ("All files", "*.*"),
]


class NewProjectDialog(tk.Toplevel):
    """Modal dialog for creating a new project."""

    def __init__(self, parent: tk.Misc, on_create: Callable[[str, Path], None]) -> None:
        super().__init__(parent)
        self.title("New Project")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._on_create = on_create
        self._result: Optional[tuple[str, Path]] = None

        body = ttk.Frame(self, padding=16)
        body.grid(row=0, column=0, sticky="nsew")

        ttk.Label(body, text="Project name:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._name_var = tk.StringVar()
        name_entry = ttk.Entry(body, textvariable=self._name_var, width=40)
        name_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        name_entry.focus_set()

        ttk.Label(body, text="Location:").grid(row=2, column=0, sticky="w", pady=(0, 4))
        self._location_var = tk.StringVar(value=str(Path.cwd()))
        location_entry = ttk.Entry(body, textvariable=self._location_var, width=32)
        location_entry.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        ttk.Button(body, text="Browse…", command=self._browse_location).grid(
            row=3, column=1, padx=(8, 0), pady=(0, 12)
        )

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Create", command=self._submit).pack(side="right")

        body.columnconfigure(0, weight=1)
        self.bind("<Return>", lambda _event: self._submit())
        self.bind("<Escape>", lambda _event: self.destroy())

        self.update_idletasks()
        self._center_over(parent)

    def _center_over(self, parent: tk.Misc) -> None:
        parent.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

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
            messagebox.showerror(
                "Invalid location",
                f"Folder not found:\n{location}",
                parent=self,
            )
            return

        self._on_create(name, location)
        self.destroy()


class ImportVideoDialog(tk.Toplevel):
    """Modal dialog for importing a video with an optional display name."""

    def __init__(
        self,
        parent: tk.Misc,
        on_import: Callable[[Path, Optional[str]], None],
    ) -> None:
        super().__init__(parent)
        self.title("Import Video")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._on_import = on_import

        body = ttk.Frame(self, padding=16)
        body.grid(row=0, column=0, sticky="nsew")

        ttk.Label(body, text="Video file:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._file_var = tk.StringVar()
        file_entry = ttk.Entry(body, textvariable=self._file_var, width=36)
        file_entry.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ttk.Button(body, text="Browse…", command=self._browse_file).grid(
            row=1, column=1, padx=(8, 0), pady=(0, 12)
        )

        ttk.Label(body, text="Display name (optional):").grid(
            row=2, column=0, sticky="w", pady=(0, 4)
        )
        self._name_var = tk.StringVar()
        ttk.Entry(body, textvariable=self._name_var, width=40).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, 12)
        )

        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(buttons, text="Import", command=self._submit).pack(side="right")

        body.columnconfigure(0, weight=1)
        self.bind("<Return>", lambda _event: self._submit())
        self.bind("<Escape>", lambda _event: self.destroy())

        self.update_idletasks()
        self._center_over(parent)

    def _center_over(self, parent: tk.Misc) -> None:
        parent.update_idletasks()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        self.geometry(f"+{x}+{y}")

    def _browse_file(self) -> None:
        file_path = filedialog.askopenfilename(
            parent=self,
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
            messagebox.showwarning(
                "Missing file",
                "Choose a valid video file to import.",
                parent=self,
            )
            return

        display_name = self._name_var.get().strip() or None
        self._on_import(file_path, display_name)
        self.destroy()


class MomentApp:
    """Main application window for Moment."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Moment")
        self.root.minsize(720, 420)
        self.root.geometry("900x520")

        self.service = ProjectService()
        self._busy = False

        self._build_menu()
        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()

        self._set_project_loaded(False)
        self._try_restore_last_project()

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project…", command=self.new_project, accelerator="Ctrl+N")
        file_menu.add_command(label="Open Project…", command=self.open_project, accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Import Video…", command=self.import_video, accelerator="Ctrl+I")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

        self.root.bind("<Control-n>", lambda _e: self.new_project())
        self.root.bind("<Control-o>", lambda _e: self.open_project())
        self.root.bind("<Control-i>", lambda _e: self.import_video())

    def _build_toolbar(self) -> None:
        toolbar = ttk.Frame(self.root, padding=(12, 8, 12, 0))
        toolbar.pack(fill="x")

        ttk.Button(toolbar, text="New Project", command=self.new_project).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Open Project", command=self.open_project).pack(side="left", padx=(0, 6))
        self._import_btn = ttk.Button(toolbar, text="Import Video", command=self.import_video)
        self._import_btn.pack(side="left")

    def _build_main_area(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        header = ttk.LabelFrame(container, text="Project", padding=12)
        header.pack(fill="x", pady=(0, 12))

        self._project_name_var = tk.StringVar(value="No project open")
        self._project_path_var = tk.StringVar(value="")
        ttk.Label(header, textvariable=self._project_name_var, font=("Segoe UI", 11, "bold")).pack(
            anchor="w"
        )
        ttk.Label(header, textvariable=self._project_path_var, foreground="#555555").pack(
            anchor="w", pady=(4, 0)
        )

        clips_frame = ttk.LabelFrame(container, text="Clips", padding=12)
        clips_frame.pack(fill="both", expand=True)

        columns = ("display_name", "frames", "fps", "flags", "clip_id")
        self._clip_tree = ttk.Treeview(
            clips_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self._clip_tree.heading("display_name", text="Name")
        self._clip_tree.heading("frames", text="Frames")
        self._clip_tree.heading("fps", text="FPS")
        self._clip_tree.heading("flags", text="Flags")
        self._clip_tree.heading("clip_id", text="Clip ID")

        self._clip_tree.column("display_name", width=220, stretch=True)
        self._clip_tree.column("frames", width=80, anchor="e")
        self._clip_tree.column("fps", width=70, anchor="e")
        self._clip_tree.column("flags", width=60, anchor="e")
        self._clip_tree.column("clip_id", width=180, stretch=True)

        scrollbar = ttk.Scrollbar(clips_frame, orient="vertical", command=self._clip_tree.yview)
        self._clip_tree.configure(yscrollcommand=scrollbar.set)
        self._clip_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._empty_label = ttk.Label(
            clips_frame,
            text="No clips yet. Use Import Video to add one.",
            foreground="#777777",
        )

    def _build_status_bar(self) -> None:
        status_frame = ttk.Frame(self.root, padding=(12, 6))
        status_frame.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Ready")
        ttk.Label(status_frame, textvariable=self._status_var).pack(anchor="w")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._import_btn.configure(state=state)
        if message:
            self._status_var.set(message)
        elif not busy:
            self._status_var.set("Ready")

    def _set_project_loaded(self, loaded: bool) -> None:
        state = "normal" if loaded else "disabled"
        self._import_btn.configure(state=state)

    def _try_restore_last_project(self) -> None:
        project_path = load_active_project_path()
        if project_path and project_path.is_dir():
            try:
                self._load_project_at(project_path)
            except ProjectServiceError:
                pass

    def new_project(self) -> None:
        """Open the new-project dialog."""
        if self._busy:
            return
        NewProjectDialog(self.root, on_create=self._create_project)

    def _create_project(self, name: str, base_dir: Path) -> None:
        try:
            self.service = ProjectService()
            project_file = self.service.create_new_project(name, base_dir=base_dir)
            assert self.service.project_path is not None
            save_active_project_path(self.service.project_path)
            self._refresh_project_view(project_file.project.name)
            self._status_var.set(f"Created project “{project_file.project.name}”")
        except ProjectServiceError as exc:
            messagebox.showerror("Create project failed", str(exc), parent=self.root)

    def open_project(self) -> None:
        """Open an existing ``.clip`` project folder."""
        if self._busy:
            return
        directory = filedialog.askdirectory(
            parent=self.root,
            title="Open Moment project (.clip folder)",
            initialdir=str(Path.cwd()),
        )
        if not directory:
            return
        try:
            self._load_project_at(Path(directory))
        except ProjectServiceError as exc:
            messagebox.showerror("Open project failed", str(exc), parent=self.root)

    def _load_project_at(self, project_path: Path) -> None:
        self.service = ProjectService(project_path)
        project_file = self.service.load_project()
        save_active_project_path(project_path)
        self._refresh_project_view(project_file.project.name)
        self._status_var.set(f"Opened project “{project_file.project.name}”")

    def import_video(self) -> None:
        """Open the import-video dialog."""
        if self._busy or self.service.project is None:
            if self.service.project is None:
                messagebox.showinfo(
                    "No project",
                    "Create or open a project before importing video.",
                    parent=self.root,
                )
            return
        ImportVideoDialog(self.root, on_import=self._start_import)

    def _start_import(self, file_path: Path, display_name: Optional[str]) -> None:
        self._set_busy(True, f"Importing {file_path.name}…")

        def worker() -> None:
            try:
                clip = self.service.import_video(file_path, display_name=display_name)
                self.root.after(0, lambda: self._on_import_success(clip))
            except ProjectServiceError as exc:
                self.root.after(0, lambda: self._on_import_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_import_success(self, clip: Clip) -> None:
        self._refresh_clip_list()
        self._set_busy(False)
        self._status_var.set(f"Imported “{clip.display_name}”")

    def _on_import_error(self, message: str) -> None:
        self._set_busy(False)
        messagebox.showerror("Import failed", message, parent=self.root)

    def _refresh_project_view(self, project_name: str) -> None:
        assert self.service.project_path is not None
        self._project_name_var.set(project_name)
        self._project_path_var.set(str(self.service.project_path))
        self._set_project_loaded(True)
        self._refresh_clip_list()

    def _refresh_clip_list(self) -> None:
        for item in self._clip_tree.get_children():
            self._clip_tree.delete(item)

        project = self.service.project
        if project is None:
            self._empty_label.place(relx=0.5, rely=0.5, anchor="center")
            return

        clips = self.service.list_clips()
        if not clips:
            self._empty_label.place(relx=0.5, rely=0.5, anchor="center")
            return

        self._empty_label.place_forget()
        for clip in clips:
            resource = project.resources.get(clip.resource_id)
            frames = resource.duration_frames if resource else 0
            fps = f"{resource.fps:.2f}" if resource else "—"
            self._clip_tree.insert(
                "",
                "end",
                iid=clip.id,
                values=(
                    clip.display_name,
                    frames,
                    fps,
                    len(clip.flags),
                    clip.id,
                ),
            )


def main() -> int:
    """Launch the Moment GUI."""
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    MomentApp(root)
    root.mainloop()
    return 0


def entrypoint() -> None:
    """Console script entry point for ``pip install -e .``."""
    raise SystemExit(main())

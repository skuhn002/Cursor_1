# Moment

A lightweight, **flag-driven** video editor. Moment organizes work around projects, imported video clips, and frame-based **flags** (annotations you place on specific frames).

This is an early MVP: project management, video import, and flag storage are in place. Timeline editing and playback UI are planned next.

---

## Features

- **Project folders** — self-contained `.clip` bundles with metadata and media
- **Video import** — copies originals, probes metadata, generates poster thumbnails
- **Frame-based flags** — mark exact frames with notes, colors, and types
- **CLI** — scriptable commands for automation and quick testing
- **GUI** — simple desktop app for creating projects and importing video

---

## Requirements

- **Python 3.10+**
- **Windows, macOS, or Linux**
- tkinter (included with standard Python on Windows and most Linux builds; on macOS, use a Python build that includes tkinter)

---

## Installation

Clone the repository and install dependencies:

```bash
git clone <your-repo-url>
cd moment

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Optional — install in editable mode with CLI entry points:

```bash
pip install -e .
```

After editable install you can run `moment` and `moment-gui` from anywhere in your virtualenv.

---

## Quick start

All commands assume you are in the project root with your virtualenv activated.

### GUI (recommended for first use)

```bash
python -m src.gui
```

1. Click **New Project** — enter a name and choose where to save it.
2. Click **Import Video** — pick a file and optionally set a display name.
3. Imported clips appear in the table with frame count, FPS, and flag count.

The GUI remembers your last open project via `.moment.json` in the current working directory.

### CLI

```bash
# Create a project (writes .moment.json as the active project)
python -m src.cli create "My Test Project"

# Import a video
python -m src.cli import "C:\path\to\video.mp4" "Intro"

# List clips
python -m src.cli list

# Add a flag at frame 245
python -m src.cli addflag clip_abc123 245 "Add title here" --color "#EF4444" --type title

# Inspect a clip
python -m src.cli info clip_abc123
```

Use `--project path\to\Project.clip` on any command to target a specific project instead of the active one.

---

## Project on disk

Each project is a folder ending in `.clip`:

```
My_Test_Project.clip/
├── project.json          # project metadata, clips, flags
└── resources/
    └── video_a1b2c3d4/
        ├── original/     # copied source video
        ├── versions/     # future edited outputs
        └── thumbnails/   # poster.jpg
```

`project.json` holds the canonical state. Media files live under `resources/` so projects are portable and easy to back up.

---

## CLI reference

| Command | Description |
|---------|-------------|
| `create <name> [-d DIR]` | Create a new project in `DIR` (default: current directory) |
| `import <video> [display_name]` | Import a video into the active project |
| `addflag <clip_id> <frame> [note] [--color HEX] [--type TYPE]` | Add a flag to a clip |
| `list` | List all clips in the active project |
| `info <clip_id>` | Show clip details and flags |

---

## Architecture

Moment follows a simple layered layout:

```
src/
├── models.py              # Pure Pydantic data models (no I/O)
├── project_state.py       # Active-project pointer (.moment.json)
├── api/
│   └── project_service.py # Business logic and file operations
├── cli.py                 # Command-line interface
└── gui/
    └── app.py             # tkinter desktop UI
```

| Layer | Responsibility |
|-------|----------------|
| **Models** | `Resource`, `Flag`, `Clip`, `Project`, `ProjectFile` — validation and serialization only |
| **ProjectService** | Create/load/save projects, import video, manage flags |
| **CLI / GUI** | User interaction; delegates all domain work to `ProjectService` |

**Timing model:** frame numbers are the primary unit. FPS is stored on each resource for display and future timecode conversion.

---

## For developers

### Running from source

```bash
python -m src.cli --help
python -m src.gui
```

### Key modules

- **`src/models.py`** — rename or extend models here; keep them free of filesystem code.
- **`src/api/project_service.py`** — add new domain operations (e.g. delete clip, export) here.
- **`src/project_state.py`** — shared active-project path used by CLI and GUI.

### Adding a feature

1. Extend models in `models.py` if the data shape changes.
2. Implement logic in `ProjectService`.
3. Expose via CLI (`cli.py`) and/or GUI (`gui/app.py`) as needed.
4. Update this README if user-facing behavior changes.

### Dependencies

| Package | Purpose |
|---------|---------|
| [Pydantic v2](https://docs.pydantic.dev/) | Data validation and JSON serialization |
| [OpenCV](https://opencv.org/) (headless) | Video metadata probing and thumbnail extraction |

OpenCV is optional at runtime for metadata/thumbnails — the service falls back to safe defaults if OpenCV is unavailable, but you should install it for normal use.

### Local files ignored by git

- `.moment.json` — pointer to your last active project
- `*.clip/` — project folders with imported media

Create test projects anywhere outside the repo, or in the repo root (they are gitignored).

---

## Roadmap

- [ ] Timeline / playback UI
- [ ] Flag editing in the GUI
- [ ] Clip trimming and version exports
- [ ] Plugin or script hooks for flag-driven automation

---

## License

MIT — see [LICENSE](LICENSE).

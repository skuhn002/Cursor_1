# Moment

A lightweight, **flag-driven** video editor. Moment organizes work around projects, imported video clips, and frame-based **flags** (annotations you place on specific frames).

This is an early MVP: project management, video import, flag-based cropping, and in-GUI clip preview are in place.

---

## Features

- **Project folders** — self-contained `.clip` bundles with metadata and media
- **Video import** — copies originals, probes metadata, generates poster thumbnails
- **Frame-based flags** — mark exact frames with notes, colors, and types
- **Flag-driven cropping** — trim a clip to the range between two flags (creates a new clip)
- **Clip preview** — play back and scrub selected clips in the GUI
- **CLI** — scriptable commands for automation and quick testing
- **GUI** — desktop app for projects, import, flags, cropping, and preview

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
4. Select a clip to preview it — use **Play/Pause**, **Stop**, and the frame scrubber.
5. Select a clip → **Add Flag** (`Ctrl+F`) to mark frames while scrubbing in the preview.
6. Select a clip → **Crop Between Flags** (`Ctrl+K`) to create a trimmed copy.

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

# Crop between two flags (creates a new clip)
python -m src.cli crop clip_abc123 flag_start_id flag_end_id --name "Intro trimmed"
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
        ├── versions/     # cropped outputs (e.g. crop_120_480_*.mp4)
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
| `crop <clip_id> <start_flag_id> <end_flag_id> [--name NAME]` | Crop between two flags; creates a new clip |

---

## Flags and cropping

Moment uses **frame numbers** as the primary timing unit. A **flag** is a marker on a specific frame of a clip — it can carry a note, color, and type (e.g. `general`, `title`). Flags are the main way to define edit points, especially for cropping.

### Adding flags

**CLI** — place a flag on a frame (use `info` to see flag IDs):

```bash
python -m src.cli addflag clip_abc123 0 "Opening shot"
python -m src.cli addflag clip_abc123 245 "Title ends" --color "#EF4444" --type title
python -m src.cli info clip_abc123
```

**GUI** — select a clip, scrub the preview to the frame you want, then **Clip → Add Flag…** (or **Add Flag** / `Ctrl+F`).

### Cropping between flags

Cropping extracts the **inclusive frame range** between a start flag and an end flag and writes a new video file. The **original clip is not modified** — Moment creates a **new clip** that points to the cropped file in `resources/.../versions/`.

**How the range is resolved:**

| Rule | Behavior |
|------|----------|
| Inclusive range | Both the start and end flag frames are included in the output |
| Start/end of clip | A flag at frame `0` crops from the beginning; a flag at or past the last frame crops to the end |
| Out-of-range flags | Flag frames are clamped to `0 … last frame` |
| Reversed flags | If the start flag is after the end flag, their frames are swapped automatically |

**CLI example:**

```bash
# Mark in and out points, then crop
python -m src.cli addflag clip_abc123 120 "In"
python -m src.cli addflag clip_abc123 480 "Out"
python -m src.cli info clip_abc123          # copy flag IDs from output
python -m src.cli crop clip_abc123 flag_in_id flag_out_id --name "Middle section"
```

**GUI** — select a clip → **Clip → Crop Between Flags…** (`Ctrl+K`). Choose a **start** and **end** from the dropdown. The list always includes:

- **Start of clip (frame 0)**
- **End of clip (last frame)**
- Any flags you have added on that clip

You can crop to the full clip, a segment between two custom flags, or from a flag to an edge (e.g. flag → end of clip) without placing a flag on frame 0 or the last frame.

### What you get after a crop

```
resources/video_a1b2c3d4/
├── original/intro.mp4              # untouched source
└── versions/
    └── crop_120_480_a1b2c3d4.mp4   # new trimmed file
```

The new clip appears in the project with trim metadata (`trim_start_frame`, `trim_end_frame`) and previews the version file, not the full original.

### Typical workflow

1. Import a video → creates a clip.
2. Scrub the preview and add flags at the frames you care about.
3. Crop between two flags (or between a flag and a clip edge).
4. Preview the cropped clip in the GUI, or inspect it with `python -m src.cli info <clip_id>`.

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

- [ ] Flag editing and deletion in the GUI
- [ ] Timeline with flag markers overlaid on the scrubber
- [ ] Plugin or script hooks for flag-driven automation

---

## License

MIT — see [LICENSE](LICENSE).

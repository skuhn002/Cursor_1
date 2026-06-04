# Moment architecture

Moment is built around **clips** as the primary unit of editing. Everything else supports creating, transforming, and ordering those clips.

## Core philosophy

### Clips are central

A **clip** is an isolated, self-contained timeline item:

- It references exactly one **resource** (media on disk).
- It owns its **flags** (frame markers on that clip’s timeline).
- It may point at a derived **version** file (crop, image still encoded as video).
- It has a **display name** and stable **id**.

Most features should read and write **clips**, not resources directly. Resources are storage; clips are the product.

### Composition is only isolated clips

The **composition** is the ordered playback sequence. It contains nothing except **clip IDs**, each referring to one whole clip already in the project.

The composition does **not**:

- Embed media paths, frame ranges, or flags.
- Reference resources directly.
- Share state between entries (no “one entry, two clips”).

Each slot is one isolated clip, played in order. Preview and (future) export walk `composition → clip → resource path`.

### Workspace vs composition

| Pool | Meaning |
|------|---------|
| **All clips** (`project.clips`) | Every clip that exists in the project. |
| **Workspace** | Clips not currently in the composition (library / alternates). |
| **Composition** | Clips chosen for the current sequence, in order. |

Importing video creates a workspace clip. Adding to the composition only **references** that clip by id. Removing from the composition does not delete the clip.

**Duplicate clip** copies the clip’s resource folder (`original/`, `versions/`, `thumbnails/`) to a new resource and creates a new workspace clip with the same flags, trim, and version metadata. Use this for parallel edits (e.g. one copy for voice-over experiments, one unchanged).

## Data model

```
Project
├── resources: dict[id, Resource]   # files + technical metadata
├── clips:      dict[id, Clip]      # editable isolated units
└── composition: Composition        # ordered clip_ids[]
```

```
Resource (vault)          Clip (edit unit)              Composition (sequence)
─────────────────       ─────────────────────         ──────────────────────
original/               resource_id ───────────────►  [ clip_A, clip_B, clip_C ]
versions/               flags[]
thumbnails/             version_filename?
                        trim metadata
```

## Layering

| Layer | Role |
|-------|------|
| `.clip/` folder | Portable bundle: `project.json` + `resources/` |
| `Project` (Pydantic) | Canonical state in `project.json` |
| `ProjectService` | Mutations, path resolution, validation |
| CLI / GUI | Call service; never own composition rules ad hoc |

## Scaling along this model

Safe extensions that preserve the philosophy:

1. **Richer composition slots** — e.g. `{ "clip_id", "offset_frames" }` still one clip per slot.
2. **Non-destructive trim** — in/out on the clip, same `clip_id` in composition.
3. **Tracks** — multiple ordered lists of clip ids (still isolated clips per cell).
4. **Export** — fold composition order into a render graph; clips stay the source of truth.

Avoid putting edit semantics on `composition` or `resources` when they belong on `Clip`.

## Baking a composition into a clip

**Goal:** Treat the current sequence as one larger unit — add flags, crop, and place it in another composition — without breaking the rule that every composition slot is a single, existing clip id.

### Recommended pattern: render, then clip

Do **not** put a “composition” inside `composition.clip_ids` as a special entry type. Instead:

1. **Render** the ordered composition to one media file (new resource under `resources/comp_xxxx/`).
2. **Create a normal clip** pointing at that resource (same shape as import/crop).
3. **Record provenance** on the clip so you can trace what was baked (optional UI: “expand lineage”).

After baking, editing is ordinary clip editing: flags and crops use frame indices on the **baked** timeline. The inner clips stay in the project unchanged; the composition can be cleared, kept for reference, or duplicated before bake.

```
Before bake:
  composition → [ clip_A, clip_B, clip_C ]
  each clip → resource / flags / versions

Bake:
  render(composition) → resources/comp_…/versions/baked_….mp4
  new clip_D → resource_id = comp resource, version = baked file

After bake:
  clip_D.flags[]     ← edit the “larger whole” here
  composition → [ …, clip_D, … ]   ← still only clip ids
```

This keeps **clips central**: the composition is a recipe; the baked output is another isolated clip.

### Suggested model fields

Add provenance on `Clip`, not a second composition type:

| Field | Purpose |
|-------|---------|
| `clip_kind: "standard" \| "baked"` | Optional; default `standard` |
| `baked_from_clip_ids: list[str]` | Snapshot of source clip ids at bake time (order preserved) |
| `baked_at: datetime` | When the bake was created |

Keep a single `resource_id` and `version_filename` for playback — same as today. A baked clip is not a live nested timeline in v1; it is a **derived asset** like a crop.

Avoid `Clip.nested_composition: list[str]` as the long-term primary model unless you invest in virtual timelines (below). Prefer bake + provenance first.

### Service API (conceptual)

| Operation | Responsibility |
|-----------|----------------|
| `render_composition(project, clip_ids?, fps?)` | Walk `list_composition_clips()` (or a passed id list), concat/decode to one file |
| `bake_composition_to_clip(name, …)` | Render → new Resource + new Clip + provenance fields |
| `get_clip_video_path(clip)` | Unchanged for baked clips (plays baked file) |

Render can live in `src/api/render.py` or `video.py`, called only from `ProjectService`. Reuse the same path resolution and OpenCV/ffmpeg stack you use for crop and image clips.

### Frame math

Define a **composition timeline** for the bake only:

- `total_frames = sum(child.duration_frames)` (later: subtract overlaps if you add transitions).
- Baked clip’s `resource.duration_frames` and `fps` come from the render output, not manual sums.
- Flags on `clip_D` are always **0 … total_frames−1** on the baked file — no cross-clip frame mapping in v1.

That is what makes “edit as a larger whole” straightforward: one clip, one frame space.

### Where the baked clip lives

| Choice | Recommendation |
|--------|----------------|
| Workspace vs composition | Default **workspace** after bake (user explicitly adds to composition). Optionally “replace composition with baked clip” as an advanced action. |
| Source composition | Keep, clear, or save as a named snapshot in provenance — user choice in UI; don’t delete source clips automatically. |

### Phase 2 (optional): compound clip without baking

If you need **non-destructive** “one timeline” before render:

- Add `clip_kind: "compound"` with `compound_clip_ids: list[str]` (ordered).
- Preview: reuse composition playback logic on those ids.
- Flags on a compound clip require a **virtual frame map**: global frame → `(child_clip_id, local_frame)`.

That is significantly more complex (flag UI, crop, export). Treat it as a second phase. For “edit as a larger whole,” **bake-first** matches your current stack and crop/image patterns.

### What to avoid

- **Composition slots that reference compositions** — breaks “isolated clips only” and complicates export.
- **Flags stored on the composition object** — flags belong on clips; the baked clip holds flags for the merged timeline.
- **Baking in place over source clips** — always new resource + new clip id so originals and alternates stay intact.

### Scaling chain

Nested edits stay clip-centric:

```
clips A, B, C  →  composition  →  bake  →  clip D (baked)
clip D         →  flags / crop  →  clip D' (version)
clip D'        →  added to another composition  →  bake  →  clip E
```

Each level is still: resources hold bytes, clips hold edits, composition holds ordered clip ids.


| Concept | Primary location |
|---------|------------------|
| `Clip`, `Resource`, `Composition` | `src/models.py` |
| Composition mutations | `Composition` methods + `ProjectService` |
| Composition merge (concat video + audio, remapped flags) | `src/api/merge.py`, `src/api/ffmpeg_util.py`, `merge_composition_to_clip()` |
| Playback order | `ProjectService.list_composition_clips()` |
| Preview | `ClipPreviewPanel.load_composition()` |
| Per-clip editing (voice-over, flags, crop) | `ClipEditorWindow`, `ProjectService.apply_voiceover_to_clip()` |
| App-wide edit preferences | `src/user_settings.py` (e.g. voice-over mix vs overwrite) |

## Clip-centric editing

Composition and workspace are **selection pools**. Most edits happen on **one clip at a time**:

1. Select a clip in the sidebar.
2. Open the **clip editor** (separate window) for focused preview and tools.
3. Mutations write back to that clip (new `versions/` file, updated flags, etc.) without changing composition order.

The main window stays the project hub; the editor window is the working surface for a single `clip_id`.

### Voice-over (v1)

| Step | Behavior |
|------|----------|
| Record | Microphone captured while the clip plays in the editor (mix mode plays existing audio; overwrite mode plays video only). |
| Mode | **Overwrite** — replace the clip’s audio track. **Mix** — combine with existing audio via ffmpeg `amix`. |
| Prompt | Modal on first use; optional **Remember my choice** stored in user settings (not `project.json`). |
| Output | Overwrites `resources/…/versions/current.mp4`; same clip’s `version_filename` set to `current.mp4`. Unreferenced files in `versions/` are removed. |

Future clip tools (color, speed, subtitles) should follow the same pattern: editor window → service API → version file on the clip.

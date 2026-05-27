# Architecture

## Overview

SciIm Toolkit is a PySide6 desktop application for scientific imaging workflows, primarily targeting MA-XRF (Macro X-Ray Fluorescence) analysis of artworks. The application follows a session-centric architecture: a single `ProjectSession` dataclass is the shared mutable state passed to all tabs via a `set_session()` injection pattern, with tabs emitting `session_changed` signals up to `MainWindow` which persists to disk.

## Component Map

```
main.py
  └── MainWindow (QMainWindow)
        ├── [Tab] ProjectSetupTab        — artwork metadata input
        ├── [Tab] ImagingPlannerTab      — tile planning for IRR/X-ray/MA-XRF
        ├── [Tab] MA-XRF Tools (QTabWidget, nested)
        │     ├── MapSetupTab            — folder ingest, file copy, manifest
        │     ├── MaxrfCorrectionsTab    — 3-layer correction editor (pyqtgraph)
        │     ├── MaxrfFalseColourTab    — per-element false-colour assignment
        │     ├── MaxrfEditTab (Overlay) — n-layer compositing with blend modes
        │     └── MaxrfCompileTab        — final export/compile
        └── [Tab] RegistrationTab        — manual point-pair image registration

Services (stateless, no UI):
  session_io.py     — JSON save/load of ProjectSession
  user_settings.py  — per-user prefs (autosave, recent projects)

Pure computation:
  maxrf_corrections/pipeline.py       — correction algorithm (numpy/scipy)
  maxrf_corrections/image_io.py       — image read/normalize utilities
  registration/registration_service.py — affine/homography solve (OpenCV)
  imaging_planner/planner_service.py  — tile layout calculation
```

## Data Flow

1. **Session injection**: `MainWindow.__init__()` creates `ProjectSession()`, calls `tab.set_session(session)` on every tab. Tabs store the reference.
2. **User edits**: Tab writes into `self.session.*`, calls `self.session.touch()`, emits `session_changed`.
3. **MainWindow response**: `_on_session_changed()` sets dirty flag, updates title bar; autosave timer flushes to disk.
4. **File open/new**: `MainWindow` calls `load_session()` to get a new `ProjectSession`, then re-injects via `set_session()` on all tabs.
5. **MA-XRF folder load**: Special case — `MapSetupTab` emits `folder_loaded`, triggering `_on_maxrf_folder_loaded()` which re-injects session into all MA-XRF subtabs so they refresh from the new `project_root`.

## Design Patterns Used

- **Shared mutable state via injection**: `ProjectSession` is passed by reference; tabs mutate it directly, not via commands or events. Simpler than MVVM but offers no undo.
- **Signal/slot for cross-component events**: `session_changed` signal (no payload) is the only cross-boundary event. Coarse-grained but sufficient.
- **`_is_loading_ui` guard**: Used in `ProjectSetupTab` and elsewhere to suppress signals during programmatic UI population (prevents feedback loops).
- **`_is_syncing_layer_ui` guard**: Same pattern in `MaxrfEditTab` for slider/spinbox synchronization.
- **Service module = pure functions + dataclasses**: `pipeline.py`, `registration_service.py`, `planner_service.py` have no Qt dependency — testable in isolation.
- **`set_session()` as the refresh/hydrate entry point**: Each tab fully rebuilds its UI state from session in `set_session()`. This doubles as the "open project" handler.

## Key Boundaries / Interfaces

| Boundary | Contract |
|---|---|
| `Tab.set_session(session)` | Tab must re-hydrate UI from session; must not emit `session_changed` during this call |
| `Tab.session_changed` signal | Emitted after any user edit that mutates session; no payload |
| `SessionIO.save_session / load_session` | Raises `SessionIOError` on failure; caller shows dialog |
| `pipeline.compute_corrected()` | Pure numpy function; no I/O, no Qt |
| `registration_service.solve_transform()` | Pure; raises `ValueError` if insufficient points |
| `manifest.json` | Shared file contract between `MapSetupTab` (writer) and downstream MA-XRF tabs (readers) |

## What's Missing / Incomplete

- **Undo/redo**: No command pattern; edits are irreversible within a session.
- **Background threading**: All image processing (corrections, compositing) runs on the main thread — UI will freeze on large maps.
- **`MaxrfCompileTab`**: Newly added file, implementation likely stub or early-stage.
- **`ProjectSetupTab`**: Newly added file (untracked in git); may lack full wiring to session model.
- **Registration tab**: Newly added; `registration_service.py` is solid but UI wiring to full session save/restore may be incomplete.
- **Duplicate `CorrectionParams`**: Defined in `pipeline.py`; a separate definition exists inside `maxrf_corrections/ui.py` — these must stay in sync manually.
- **No progress reporting**: Long file copies (Map Setup ingest) and correction batches have no progress dialog or cancellation.

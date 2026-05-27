# Structure

## Directory Tree (annotated)

```
sciim-toolkit/
├── src/sciim_toolkit/          # Main package
│   ├── __init__.py
│   ├── app/
│   │   ├── main.py             # Entry point: QApplication setup, MainWindow launch
│   │   └── main_window.py      # MainWindow: tab wiring, menu, session lifecycle, autosave
│   ├── models/
│   │   └── project.py          # All session dataclasses: ProjectSession, MaxrfPipelineState,
│   │                           #   RegistrationState, ImagingPlannerState, etc.
│   ├── services/
│   │   ├── session_io.py       # save_session / load_session (JSON, raises SessionIOError)
│   │   └── user_settings.py    # UserSettings dataclass, platform-aware config dir, autosave drafts
│   └── features/
│       ├── common/
│       │   └── placeholder.py  # Shared placeholder widget (used while features are stub)
│       ├── imaging_planner/
│       │   ├── __init__.py     # Re-exports ImagingPlannerTab
│       │   ├── ui.py           # ImagingPlannerTab: tile layout UI, painting image viewer
│       │   └── planner_service.py  # Pure: tile count / overlap calculation
│       ├── maxrf_corrections/
│       │   ├── __init__.py     # Re-exports MaxrfCorrectionsTab
│       │   ├── ui.py           # MaxrfCorrectionsTab: 3-layer correction editor (pyqtgraph)
│       │   ├── pipeline.py     # Pure: CorrectionParams, apply_one_correction, compute_corrected
│       │   ├── image_io.py     # Pure: read_image, normalize_feature, resize_to, robust_minmax
│       │   └── drawing_widget.py  # PolygonDrawingWidget: interactive ROI drawing on images
│       ├── maxrf_edit/
│       │   ├── __init__.py     # Re-exports MapSetupTab, MaxrfEditTab, MaxrfFalseColourTab, MaxrfCompileTab
│       │   ├── map_setup_tab.py    # MapSetupTab: folder ingest, file copy to workspace, manifest write
│       │   ├── ui.py               # MaxrfEditTab (Overlay): n-layer compositing, blend modes, heatmap
│       │   ├── false_colour_tab.py # MaxrfFalseColourTab: per-element colour assignment
│       │   └── compile_tab.py      # MaxrfCompileTab: final export (new, may be stub)
│       ├── project_setup/
│       │   ├── __init__.py     # Re-exports ProjectSetupTab
│       │   └── ui.py           # ProjectSetupTab: artwork metadata form (new, untracked)
│       └── registration/
│           ├── __init__.py     # Re-exports RegistrationTab
│           ├── registration_service.py  # Pure: solve_transform (affine/homography), warp_to_target
│           └── ui.py           # RegistrationTab: point-pair UI, overlay preview (new, untracked)
├── archive/
│   └── cleanup_2026-02-21/
│       ├── tests/              # Archived test suite (not in active test path)
│       ├── test_artifacts/     # Debug scripts, fixture generators
│       └── *.py                # Archived UI backups from a prior refactor
├── pyproject.toml              # Hatch build, dependencies, ruff config, pytest config
└── .planning/
    └── codebase/               # This map
```

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `app/main.py` | Bootstraps QApplication, sets app metadata, shows MainWindow |
| `app/main_window.py` | Owns the session; wires all tabs; handles File/Prefs menus; autosave timer |
| `models/project.py` | Single source of truth for all serializable state; `to_dict` / `from_dict` |
| `services/session_io.py` | File I/O for project files (`.sciim.json`); wraps errors |
| `services/user_settings.py` | Platform-aware XDG/macOS settings directory; autosave drafts path |
| `features/*/ui.py` | Tab widget: owns only UI widgets and session binding, delegates computation |
| `features/*/pipeline.py` | Stateless image computation; no Qt imports |
| `features/*/registration_service.py` | Stateless geometry computation; no Qt imports |

## Feature Anatomy

Each feature follows this structure:

```
features/<feature>/
├── __init__.py          # from .ui import <TabClass>; re-export pattern
├── ui.py                # Tab class inheriting QWidget
│    ├── session_changed = QtCore.Signal()    # always emitted after user edit
│    ├── __init__(parent)    # build UI, bind signals, no session yet
│    ├── _build_ui()         # construct all widgets
│    ├── _bind_signals()     # connect widget signals to handlers
│    └── set_session(session)  # hydrate UI from session; refresh state
└── [*_service.py]       # optional pure-computation module (no Qt)
```

The tab never calls `set_session()` on itself; `MainWindow` always calls it.

## Naming Conventions

- Files: `snake_case` throughout
- Tab classes: `<FeatureName>Tab` (e.g., `MaxrfEditTab`, `RegistrationTab`)
- Service modules: `<name>_service.py` or `pipeline.py`
- Signal names: `session_changed`, `folder_loaded` (snake_case, past-tense or noun)
- Private methods: leading underscore (`_build_ui`, `_on_session_changed`)
- Guard flags: `_is_loading_ui`, `_is_syncing_layer_ui`, `_is_restoring_session_stack`

## Entry Points

- CLI: `sciim-toolkit` → `sciim_toolkit.app.main:main` (defined in `pyproject.toml`)
- Direct: `python -m sciim_toolkit.app.main`
- On-disk workspace created at ingest: `<project_root>/MA-XRF_workspace/{raw_data,corrected_maps,false_coloured_maps,final_maps,overlays,metadata/logs}/`
- Project file: `*.sciim.json` (JSON, portable relative paths)
- User settings: `~/Library/Application Support/SciIm Toolkit/settings.json` (macOS)
- Autosave drafts: same dir `/autosave/untitled_autosave.sciim.json`
- False-colour presets: `~/.sciim_false_colour_presets.json` (not inside user config dir — inconsistency)

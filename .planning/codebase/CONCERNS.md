# Concerns

## Critical Issues (blockers)

1. **No `closeEvent` in `MainWindow`**: Closing the app with unsaved changes silently discards work. There is no "do you want to save?" dialog on window close — only on `new_project`. (`app/main_window.py`)

2. **Signal type mismatch on `MapSetupTab`**: `MapSetupTab.session_changed` is declared as `Signal(object)` while every other tab declares `Signal()`. `MainWindow._on_session_changed` accepts `*_args` masking the mismatch, but this breaks the interface contract.

3. **Dual session/manifest state with no reconciliation**: `ProjectSession.maxrf_pipeline.map_registry` (in-memory) and the on-disk `map_manifest.json` (written by `MapSetupTab`) are two separate representations of the same data. They are never reconciled on project load — a partial ingest or crashed export can leave them permanently diverged.

## High-Priority Technical Debt

4. **All image processing on the main thread**: `MaxrfCorrectionsTab`, `MaxrfEditTab`, and `MapSetupTab` (file copy) all execute numpy/scipy/OpenCV operations synchronously. On large MA-XRF maps (e.g., 4000×3000 TIFF), this freezes the UI for seconds with no progress feedback or cancellation.

5. **No per-element correction parameter persistence**: `MaxrfCorrectionsTab` keeps correction sliders in UI state only. Switching between element maps does not save/restore the correction parameters for each map — all correction work for an element is lost when another is selected. (`features/maxrf_corrections/ui.py`)

6. **Three storage mechanisms**: User-facing state is spread across `services/user_settings.py` (platform config dir), `~/.sciim_false_colour_presets.json` (hardcoded home dir, bypasses the service), and direct `QSettings` usage in some tab code. Should consolidate through `user_settings`.

7. **God file size**: `maxrf_corrections/ui.py` (~1500 lines) and `maxrf_edit/ui.py` (~1530 lines) contain all UI, state management, and computation with no service extraction, unlike `registration/` which properly separates `registration_service.py`. Editing either file is error-prone.

8. **Duplicate `CorrectionParams` dataclass**: Defined in `pipeline.py` (canonical) and also redefined inside `maxrf_corrections/ui.py`. These must stay in sync manually. The UI copy is the one used for session serialization.

## Incomplete Features

- **`MaxrfCompileTab`**: Newly added file (`src/sciim_toolkit/features/maxrf_edit/compile_tab.py`), implementation likely stub or early-stage. Not yet validated as functional.
- **`ProjectSetupTab`**: Newly added (untracked in git). Artwork metadata form exists; session wiring and validation completeness unclear.
- **`RegistrationTab`**: Newly added UI. `registration_service.py` (solve + warp) is solid, but session save/restore for point pairs may be incomplete.
- **`_get_fc_colour_from_manifest`** in `MaxrfEditTab`: Permanent stub — always returns `None`. Comment says "In a full implementation, we'd read from the colour profiles."
- **Auto-registration via SimpleITK**: Listed as an optional dependency in `pyproject.toml` but no code for it exists.
- **Polygon drawing tool**: `PolygonDrawingWidget` exists in `maxrf_corrections/drawing_widget.py` but integration into the corrections workflow may be incomplete.

## Design Smells

- **Element symbol detection triplicated**: Regex to extract element symbol and line family from filenames appears in at least `map_setup_tab.py`, `false_colour_tab.py`, and `maxrf_edit/ui.py`. Should be in `image_io.py` or a shared utility.
- **`set_session()` called redundantly**: On project open/new, `MainWindow` calls `set_session()` on all tabs even when only some tabs need refresh. The `_on_tab_changed` handler then calls `set_session()` again on the planner and registration tabs when they become active — double-initialisation.
- **`new_project` unsaved-change guard is incomplete**: Only checks `session.project_file or session.maxrf_pipeline.map_registry` — misses artwork metadata and registration state changes.
- **Presets file at `~/.sciim_false_colour_presets.json`**: Not inside the user config/data directory managed by `user_settings.py`. Will scatter files on the user's home directory.
- **`session.touch()` called inside `MaxrfEditTab._persist_overlay_stack_to_session`**: This bypasses the `_on_session_changed` autosave flag in `MainWindow`, meaning overlay changes may not trigger autosave.

## Missing Infrastructure

- **No active test suite**: `tests/` directory does not exist; archived tests test old API.
- **No CI pipeline**: No `.github/workflows/` — no automated linting, type-checking, or test runs on push.
- **No type-check configuration**: `mypy` or `pyright` not in dev dependencies; `ruff` configured for lint only.
- **No dependency lockfile**: `pyproject.toml` specifies only lower bounds; no `uv.lock` or `requirements.lock` for reproducible installs.
- **No progress/cancellation infrastructure**: No `QThread` or `QRunnable` worker pattern established; adding background processing requires building from scratch.

## Low-Priority / Nice-to-Have

- `app/main_window.py`: `_load_user_settings()` has a hardcoded migration guard (`if settings.autosave_interval_ms == 1200`) — one-time migration code that should be removed after deployment.
- `user_settings.py` and `session_io.py` exceptions are sufficiently descriptive but have no error codes, making programmatic handling (retry, fallback) awkward.
- The `common/placeholder.py` module exists but its usage pattern across the codebase is unclear — may be dead code.

## Archived / Removed Code Notes

The `archive/cleanup_2026-02-21/` directory contains:
- `ui_v1_backup.py` and `ui_backup.py` for `maxrf_corrections` — suggests the corrections UI was significantly refactored in Feb 2026
- Two working test files for pipeline and planner — these are the only test coverage that ever existed and cover the most testable pure-function code
- Debug/fixture scripts that reveal the coordinate system issues (the `debug_coords.py` artifact) were real problems requiring investigation

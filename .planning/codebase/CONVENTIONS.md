# Conventions

## Code Style

- **Line length**: 100 characters (configured in `pyproject.toml` via Ruff)
- **Target**: Python 3.11+
- **Formatter**: Ruff (configured but not enforced in CI yet)
- `from __future__ import annotations` used consistently in every module for deferred evaluation
- Imports follow standard order: stdlib → third-party → local; local imports use `from sciim_toolkit.` absolute paths

## Type Annotations

- All public function signatures are annotated (parameters + return types)
- Dataclass fields all typed
- `Any` used sparingly and only where JSON deserialization requires it (`dict[str, Any]`)
- `| None` union syntax used throughout (Python 3.10+ style, enabled by `from __future__ import annotations`)
- `list[str]`, `dict[str, Any]` etc. — lowercase generics (3.9+ style)
- No `Optional[...]` — always `T | None`

## Error Handling Patterns

- **Service boundary errors**: Wrapped in domain exceptions (`SessionIOError`, `UserSettingsError`) with `raise ... from exc` to preserve traceback
- **UI error reporting**: `QMessageBox.warning/critical` for user-facing failures; `statusBar().showMessage(...)` for non-critical feedback
- **Silent fallbacks in computation**: Image load failures in tab code are caught with bare `except Exception` and displayed as text in the preview label — no re-raise
- **Guard flags pattern**: `_is_loading_ui`, `_is_syncing_layer_ui`, `_is_restoring_session_stack` booleans prevent signal feedback loops during programmatic UI updates

## Naming Conventions

| Pattern | Example |
|---|---|
| Tab classes | `MaxrfEditTab`, `RegistrationTab` |
| Service modules | `planner_service.py`, `registration_service.py` |
| Signal names | `session_changed`, `folder_loaded` |
| Private methods | `_build_ui`, `_bind_signals`, `_on_session_changed` |
| Guard flags | `_is_loading_ui`, `_is_syncing_layer_ui` |
| Dataclass state | `MaxrfPipelineState`, `ImagingPlannerState` |
| Error classes | `SessionIOError`, `UserSettingsError` |

## UI Patterns (signals/slots)

- All widgets constructed in `_build_ui()`, all signal connections in `_bind_signals()` — these are always separate methods called from `__init__`
- No lambda signal handlers that mutate state — lambdas used only for routing (e.g., `lambda: self.save_project(force_choose=True)`)
- `blockSignals(True/False)` used when programmatically syncing paired widgets (slider ↔ spinbox)
- Splitter + scroll area pattern used for panels with controls on one side and a preview canvas on the other
- `QGroupBox` for logical grouping of controls within a tab

## Service/Feature Separation Pattern

- Features with non-trivial computation extract it into a `*_service.py` or `pipeline.py` with **no Qt imports**
- The service module is a flat collection of pure functions + dataclasses — no classes with state
- The tab's `ui.py` owns all session state and widget state; it calls service functions for computation
- `image_io.py` in `maxrf_corrections/` acts as a shared image utility module for that feature

## Documentation Style

- Docstrings present on complex pure functions in service modules (`pipeline.py` has full Args/Returns/Algorithm docstrings)
- UI tab code is largely uncommented — widget names are descriptive
- Inline comments used sparingly for non-obvious business logic (coordinate system notes, algorithm steps)
- No TODO comments in source — known gaps tracked externally

# Testing

## Test Infrastructure

- **Test runner**: pytest (configured in `pyproject.toml`, `testpaths = ["tests"]`)
- **Active test directory**: `tests/` — **does not exist** in the repo
- **Archived test directory**: `archive/cleanup_2026-02-21/tests/` — contains 2 test files from a prior codebase state, removed during a cleanup on 2026-02-21
- **Dev dependency**: `pytest>=8.2` in `[project.optional-dependencies.dev]`
- No coverage tooling configured (`pytest-cov` not in dependencies)
- No CI pipeline (no `.github/workflows/` files present)

## Test Types Present

**Active tests**: None.

**Archived tests** (reference only — test old API, not current code):
- `archive/cleanup_2026-02-21/tests/test_corrections_pipeline.py` — unit tests for correction pipeline logic
- `archive/cleanup_2026-02-21/tests/test_planner_service.py` — unit tests for tile planning calculations

**Test artifacts** (debug/fixture scripts, not pytest tests):
- `archive/cleanup_2026-02-21/test_artifacts/inspect_tiff.py` — TIFF inspection utility
- `archive/cleanup_2026-02-21/test_artifacts/debug_coords.py` — coordinate debugging script
- `archive/cleanup_2026-02-21/test_artifacts/generate_transform_samples.py` — fixture generator for registration
- `archive/cleanup_2026-02-21/test_artifacts/create_test_image.py` — synthetic image fixture generator

## Coverage Assessment (by feature)

| Feature | Testability | Active Tests | Notes |
|---|---|---|---|
| `maxrf_corrections/pipeline.py` | High — pure functions | None | Previously tested (archived) |
| `maxrf_corrections/image_io.py` | High — pure functions | None | No tests written |
| `registration/registration_service.py` | High — pure functions | None | Archived generator scripts exist |
| `imaging_planner/planner_service.py` | High — pure functions | None | Previously tested (archived) |
| `services/session_io.py` | Medium — file I/O | None | Simple, easily tested with tmp_path |
| `services/user_settings.py` | Medium — file I/O + platform | None | Platform branching adds complexity |
| `models/project.py` | Medium — dict round-trip | None | `from_dict(to_dict())` round-trip would be high value |
| All tab UI classes | Low — requires Qt | None | Would need `pytest-qt` |

## What's Tested

Nothing in the active codebase has automated tests.

## What's NOT Tested

- Correction pipeline math (apply_one_correction, compute_corrected)
- Image I/O (read_image, normalize_feature, resize_to, robust_minmax)
- Tile planning calculation (planner_service)
- Transform solving and warp (registration_service)
- Session serialization round-trips (ProjectSession.to_dict / from_dict)
- User settings migration (legacy path → new platform path)
- Manifest parsing in MaxrfEditTab
- Element/line family detection regex in MaxrfEditTab
- Overlay stack session persistence/restore
- Autosave logic in MainWindow

## Gaps & Risks

1. **No regression safety net**: Refactoring any computation module (pipeline, registration, planner) has no automated guard.
2. **Archived tests cover old API**: Cannot simply restore them — models and function signatures have changed significantly since the cleanup.
3. **No session round-trip test**: The `ProjectSession.from_dict` parser is complex (with legacy migration paths) and untested — corrupt saves could go undetected until user data is lost.
4. **No Qt testing infrastructure**: `pytest-qt` not in dependencies, so UI tests would require setup work before any tab logic can be tested.
5. **Easiest wins**: The pure-function service modules (`pipeline.py`, `registration_service.py`, `planner_service.py`, `image_io.py`) are immediately testable with no Qt dependency and no fixtures beyond numpy arrays.

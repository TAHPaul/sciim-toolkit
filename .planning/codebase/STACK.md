# Technology Stack

**Analysis Date:** 2026-05-27

## Languages & Runtimes

**Primary:**
- Python 3.14.3 — all application code (runtime venv at `.venv`, created with Homebrew `python@3.14`)
- `requires-python = ">=3.11"` declared in `pyproject.toml`; actual runtime is 3.14

**No secondary languages** — no JavaScript, TypeScript, CSS, or shell scripts in `src/`.

## UI Framework

**Core:**
- PySide6 >= 6.7 — Qt6 bindings for Python; used for all windows, widgets, dialogs, signals/slots
  - `PySide6.QtWidgets` — layout, tab widgets, dialogs, menus (`src/sciim_toolkit/app/main_window.py`)
  - `PySide6.QtCore` — `QTimer`, `QSettings`, `Signal`, `Qt` enums (`src/sciim_toolkit/features/maxrf_edit/false_colour_tab.py`)
  - `PySide6.QtGui` — `QImage`, `QPixmap`, `QColor`, `QKeySequence`, actions (`src/sciim_toolkit/features/maxrf_edit/false_colour_tab.py`)

**Scientific Plotting:**
- pyqtgraph >= 0.13 — embedded scientific image viewer with pan/zoom; configured once at startup with `pg.setConfigOptions(imageAxisOrder="row-major")` (`src/sciim_toolkit/app/main.py`)

## Scientific / Data Libraries

**Array computation:**
- numpy >= 1.26 — core array type used throughout; all image data is `np.ndarray` (`src/sciim_toolkit/features/maxrf_corrections/image_io.py`)

**Image processing:**
- scipy >= 1.11 — `scipy.ndimage.gaussian_filter` and `scipy.ndimage.shift` used in correction pipeline (`src/sciim_toolkit/features/maxrf_corrections/pipeline.py`)
- scikit-image >= 0.22 — `skimage.transform.resize` used for bilinear image resizing (`src/sciim_toolkit/features/maxrf_corrections/image_io.py`)
- opencv-python >= 4.9 — affine/homography transform solving and warping (`cv2.getAffineTransform`, `cv2.estimateAffine2D`, `cv2.findHomography`, `cv2.warpAffine`, `cv2.warpPerspective`) in `src/sciim_toolkit/features/registration/registration_service.py`

**Image I/O:**
- tifffile >= 2024.2 — primary TIFF reader/writer; handles multi-dimensional TIFF stacks (`src/sciim_toolkit/features/maxrf_corrections/image_io.py`, `src/sciim_toolkit/features/maxrf_edit/false_colour_tab.py`)
- imageio >= 2.34 — fallback reader for PNG, JPEG, and other formats via `imageio.v3` API (`src/sciim_toolkit/features/maxrf_corrections/image_io.py`)

**Optional (registration extra):**
- SimpleITK >= 2.3 — declared as optional dependency under `[project.optional-dependencies] registration`; not yet imported anywhere in `src/`. Installed separately with `pip install sciim-toolkit[registration]`.

## Build & Packaging

**Build backend:**
- hatchling >= 1.25 — PEP 517 build backend (`pyproject.toml` `[build-system]`)
- Package source: `src/sciim_toolkit` (src-layout)
- Wheel target configured in `[tool.hatch.build.targets.wheel]`

**Entry point:**
- CLI script `sciim-toolkit` → `sciim_toolkit.app.main:main` (registered in `[project.scripts]`)

**Virtual environment:**
- `.venv/` — project-local venv, created with Homebrew Python 3.14
- No lockfile present (no `pip-tools`, `poetry.lock`, or `uv.lock`)

## Dev Tooling

**Testing:**
- pytest >= 8.2 — test runner; `testpaths = ["tests"]` in `pyproject.toml`; no active test files exist under `tests/` (only in `archive/`)

**Linting / formatting:**
- ruff >= 0.6 — single tool for linting and import sorting; `line-length = 100`, `target-version = "py311"` (`pyproject.toml` `[tool.ruff]`)

**Editor:**
- VS Code — `.vscode/settings.json` sets default Python interpreter to `.venv/bin/python`
- GitHub Copilot — `.github/copilot-instructions.md` instructs always use project-local `.venv`

**CI/CD:**
- None detected — no GitHub Actions workflows, no `.travis.yml`, no `Makefile`

## Notable Constraints

- **No lockfile** — reproducible installs require manual pinning or adding `uv`/`pip-tools`
- **Python 3.14 in venv vs. >=3.11 declared** — code uses `from __future__ import annotations` consistently, compatible back to 3.10+
- **pyqtgraph axis order** — must call `pg.setConfigOptions(imageAxisOrder="row-major")` before creating `QApplication`; done in `src/sciim_toolkit/app/main.py`
- **SimpleITK not yet wired** — optional dependency declared but zero import sites in `src/`; registration feature currently uses only OpenCV
- **No database** — all persistence is flat-file (JSON project files + filesystem directories)
- **macOS-primary development** — `.venv` uses Homebrew Python; `user_config_dir()` resolves to `~/Library/Application Support/SciIm Toolkit` on macOS

---

*Stack analysis: 2026-05-27*

# Integrations

**Analysis Date:** 2026-05-27

## File Formats (read/write)

**Project session files:**
- Format: JSON, extension `.sciim.json`
- Read: `src/sciim_toolkit/services/session_io.py` → `load_session(path)`
- Write: `src/sciim_toolkit/services/session_io.py` → `save_session(path, session)`
- Schema: serialized `ProjectSession` dataclass via `dataclasses.asdict()`; fields cover artwork metadata, imaging planner state, MA-XRF pipeline state, and registration state
- Autosave draft path: `~/Library/Application Support/SciIm Toolkit/autosave/untitled_autosave.sciim.json` (macOS)

**MA-XRF elemental map images (read):**
- TIFF / multi-page TIFF — primary format; read with `tifffile.TiffFile.asarray()` (`src/sciim_toolkit/features/maxrf_corrections/image_io.py`)
- PNG — read with `imageio.v3.imread`; converted to grayscale if RGB/RGBA
- JPEG / JPG — read with `imageio.v3.imread`; converted to grayscale
- Generic fallback for any other extension via `imageio.v3.imread`

**MA-XRF elemental map images (write):**
- TIFF — written with `tifffile.imwrite()` preserving source bit depth (`src/sciim_toolkit/features/maxrf_edit/false_colour_tab.py`)
- PNG / JPEG — written with `imageio.v3.imwrite()`; JPEG cast to uint8 if source is higher bit depth

**Colour profile files:**
- Format: JSON, extension `.json`
- Schema: `{"name": str, "colors": {element_symbol: hex_color_string}}`
- Read: `src/sciim_toolkit/features/maxrf_edit/false_colour_tab.py` → `import_colour_profile()`
- Write: `src/sciim_toolkit/features/maxrf_edit/false_colour_tab.py` → `export_colour_profile()`
- User profiles persisted locally: `~/.sciim_false_colour_profiles.json`

**Map manifest files:**
- Format: JSON, filename `map_manifest.json`
- Location within project workspace: `<project_root>/metadata/logs/map_manifest.json`
- Read/Write: `src/sciim_toolkit/features/maxrf_edit/false_colour_tab.py` → `_load_from_manifest()` / `_update_manifest_for_false_colour()`
- Schema: `{"map_registry": {map_id: {element, line_family, filename, false_colour_variants, ...}}}`

**User settings file:**
- Format: JSON, filename `settings.json`
- Location (macOS): `~/Library/Application Support/SciIm Toolkit/settings.json`
- Location (Windows): `%APPDATA%\sciim-toolkit\settings.json`
- Location (Linux): `~/.config/sciim-toolkit/settings.json`
- Legacy path (migrated automatically): `~/.sciim_toolkit/settings.json`
- Read/Write: `src/sciim_toolkit/services/user_settings.py`

## External APIs / Services

**None.** The application operates entirely offline. There are no HTTP clients, no cloud SDK imports, no REST or GraphQL calls anywhere in `src/`.

## Data Sources

**User filesystem (primary):**
- MA-XRF elemental map TIFF/PNG/JPEG files selected via `QFileDialog` by the user
- Reference photograph images (any format readable by imageio) for multimodal registration
- Project workspace directory structure created and managed by the app:
  ```
  <project_root>/
  ├── raw_data/          # copied raw elemental maps
  ├── corrected_maps/    # output of correction pipeline (suffix _corrected)
  ├── false_coloured_maps/  # false-colour exports (suffix _fc)
  ├── final_maps/        # compiled final dataset (best-available per map)
  └── metadata/
      └── logs/
          └── map_manifest.json
  ```

**Platform native settings store:**
- `QSettings("SCIIM", "MaxrfCorrections")` — stores UI widget state for Corrections tab (persisted to platform-native location by Qt)
- `QSettings("SCIIM", "MaxrfFalseColour")` — stores startup default colour profile name

## Inter-process / IPC

**None detected.** The application is single-process. No subprocess spawning, no socket communication, no shared memory, no message queues found in `src/`.

**Threading model:**
- Qt event loop runs on the main thread
- All image processing (numpy/scipy/opencv) executes synchronously on the main thread — no `QThread`, `concurrent.futures`, or `threading` usage detected. Long operations (corrections, false-colouring, compile) will block the UI.

## Gaps / Unknown Integrations

**SimpleITK — declared but unwired:**
- `SimpleITK >= 2.3` is listed as an optional dependency under `[project.optional-dependencies] registration` in `pyproject.toml`
- Zero import sites in `src/sciim_toolkit/`
- The registration feature (`src/sciim_toolkit/features/registration/`) currently uses only OpenCV for manual point-pair transforms
- Automatic/elastic registration via SimpleITK is a planned future integration (referenced in `docs/architecture.md`)

**No image export to vector or PDF formats** — the planner generates tile layouts but exports only to the session JSON; there is no SVG/PDF rendering of imaging plans.

**No network/cloud sync** — project files live entirely on the user's local disk; no Dropbox, S3, or similar integration.

**No spectral data formats** — the app handles per-element intensity maps (grayscale images) only; it does not read raw XRF spectra (`.mca`, HDF5, or proprietary scanner formats) directly.

---

*Integration audit: 2026-05-27*

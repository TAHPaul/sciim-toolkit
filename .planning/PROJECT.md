# SciIm Toolkit

## What This Is

A PySide6 desktop application for scientific imaging workflows in art conservation research. It supports MA-XRF (Macro X-Ray Fluorescence) elemental map processing — from raw map ingest through corrections, false colouring, and multi-element overlay compositing — as well as imaging tile planning for IRR, X-radiography, and MA-XRF modalities. Built for conservation scientists at museums and institutes; distributed as self-contained executables (no Python or terminal required).

## Core Value

A conservation scientist can take raw MA-XRF elemental maps, correct them, false-colour them, and composite a publication-ready overlay — all without leaving the app or writing a line of code.

## Requirements

### Validated

- ✓ Project session save/load as `.sciim.json` with recent projects menu — existing
- ✓ Autosave with configurable interval and draft fallback — existing
- ✓ User settings (autosave, recent projects) persisted to platform-appropriate config dir — existing
- ✓ Project Setup: artwork metadata form (title, artist, dimensions, inventory ID, collection) — existing
- ✓ Imaging Planner: tile layout calculation for IRR, X-radiography, and MA-XRF modalities with overlap control — existing
- ✓ MA-XRF Map Setup: folder ingest, file copy to structured workspace, manifest JSON creation — existing
- ✓ MA-XRF Corrections: interactive 3-layer correction editor (pyqtgraph) with strength/threshold/blur/shift/invert per layer — existing
- ✓ False Colouring: per-element colour assignment with named profiles — existing
- ✓ Overlay compositing: n-layer compositing with blend modes, opacity, heatmap rendering, and named presets — existing
- ✓ Overlay export: composite as PNG or TIFF — existing
- ✓ Multimodal Registration: manual point-pair image registration with affine/homography transform — existing

### Active

- [ ] Fix critical stability bugs (silent data loss on window close, signal type mismatch, dual session/manifest state)
- [ ] Eliminate main-thread image processing freezes (background threading for corrections and exports)
- [ ] Complete incomplete features: Compile tab, Registration UI, correction parameter persistence
- [ ] Establish test coverage for pure-function service modules
- [ ] Standalone macOS `.app` and Windows `.exe` build pipeline via GitHub Actions
- [ ] Per-modality registration workflow: structured flow for aligning IRR and X-radiography images to a reference photograph
- [ ] Overlay legend: optional element-symbol + colour-box legend (user-chosen corner), shown in preview and burned into export
- [ ] Colour overlap visualization: optional circles showing 2–4 element colour overlaps in the legend

### Out of Scope

- Automated image registration (SimpleITK / feature-based) — manual point-pairs only for now
- Web or server deployment — desktop-only
- Requiring Python or terminal from end users — executables must be fully self-contained
- Multi-user collaboration / shared sessions — single-user local tool

## Context

- **Domain**: MA-XRF analysis in art conservation; users are conservation scientists with deep domain expertise but zero software/Python experience
- **Distribution model**: Paul builds executables and places them on a shared institute drive; colleagues double-click to run on macOS or Windows. GitHub Actions CI will automate the cross-platform build on each tagged release.
- **Existing infrastructure**: Single git repo with one prior commit. `.github/` directory already present (untracked). Hatch build system, Ruff linting, pytest configured but no active tests.
- **Codebase health**: Several critical bugs identified (see `.planning/codebase/CONCERNS.md`). Key risk: no `closeEvent` means silent data loss. Main-thread processing causes UI freezes on large maps. No active test suite.
- **Session format**: `.sciim.json` — must remain stable and backward-compatible across versions colleagues may have cached.

## Constraints

- **Tech stack**: Python 3.11+ / PySide6 — must stay consistent; no framework changes
- **Executable packaging**: PyInstaller or Nuitka — must produce single-file or single-directory bundles with no runtime Python dependency
- **Platform**: macOS 12+ and Windows 10+ (64-bit)
- **Session compatibility**: `.sciim.json` format must remain loadable across versions — no breaking schema changes without migration
- **Build access**: Only Paul builds and deploys; no colleague should need developer tools

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| GitHub Actions for cross-platform builds | Paul has no Windows machine; CI builds both platforms on tag push, artifacts uploaded to GitHub Release for download | — Pending |
| Manual point-pair registration only (no SimpleITK auto-registration) | Auto-registration adds significant complexity and a large optional dependency; manual pairs give conservators explicit control | — Pending |
| Overlay legend optional with toggle | Conservators sometimes want clean overlays for publications; legend should be user-controlled, not always-on | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-27 after initialization*

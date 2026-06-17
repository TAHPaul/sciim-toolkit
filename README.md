# SciIm Toolkit

SciIm Toolkit is a desktop application for planning and processing scientific imaging workflows for artworks.

## Planned Modules
- Imaging Planner
- MA-XRF Corrections
- MA-XRF Edit (false colour and overlays)
- Registration

## Current Status
This repository now includes the first runnable application shell and the first functional Imaging Planner MVP.

## Quick Start
1. Create and activate the project-local `.venv` (recommended for this repo):
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2. Install dependencies:
   - `pip install -e .`
3. Run the app:
   - `sciim-toolkit`

## Standalone app (no Python needed)
Colleagues can run SciIm Toolkit as a double-click app on **macOS** and **Windows**
without installing Python or setting up a venv. Builds are produced on demand via a
manual GitHub Actions workflow ("Build executables") and published as a release with a
zip per platform. See [docs/BUILDING.md](docs/BUILDING.md) for how to trigger a build and
how to run the result.

## Project Layout
- `src/sciim_toolkit/app` - main application and window shell
- `src/sciim_toolkit/features` - feature tabs/modules
- `src/sciim_toolkit/models` - data models
- `src/sciim_toolkit/services` - IO and shared services
- `docs` - architecture and roadmap notes

## Local User Data (not in git)
SciIm Toolkit stores per-user settings and temporary autosave drafts outside the repository.

- If a project is already open/saved, autosave writes to that existing `.sciim.json` project file.
- If no project file exists yet (untitled/new session), autosave writes a local draft in the app data folder.

### Paths
- **macOS**
   - Settings: `~/Library/Application Support/SciIm Toolkit/settings.json`
   - Unsaved autosave draft: `~/Library/Application Support/SciIm Toolkit/autosave/untitled_autosave.sciim.json`
- **Linux**
   - Settings: `$XDG_CONFIG_HOME/sciim-toolkit/settings.json` (fallback: `~/.config/sciim-toolkit/settings.json`)
   - Unsaved autosave draft: `$XDG_DATA_HOME/sciim-toolkit/autosave/untitled_autosave.sciim.json` (fallback: `~/.local/share/sciim-toolkit/autosave/untitled_autosave.sciim.json`)
- **Windows**
   - Settings: `%APPDATA%/sciim-toolkit/settings.json` (fallback: `%LOCALAPPDATA%/sciim-toolkit/settings.json`)
   - Unsaved autosave draft: `%LOCALAPPDATA%/sciim-toolkit/autosave/untitled_autosave.sciim.json` (fallback: `%APPDATA%/sciim-toolkit/autosave/untitled_autosave.sciim.json`)

These files are machine-local and user-local, so they are not tracked by git and are not shared by pulling the repository.

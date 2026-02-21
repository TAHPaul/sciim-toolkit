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
1. Create and activate a Python 3.11+ environment.
2. Install dependencies:
   - `pip install -e .`
3. Run the app:
   - `sciim-toolkit`

## Project Layout
- `src/sciim_toolkit/app` - main application and window shell
- `src/sciim_toolkit/features` - feature tabs/modules
- `src/sciim_toolkit/models` - data models
- `src/sciim_toolkit/services` - IO and shared services
- `docs` - architecture and roadmap notes

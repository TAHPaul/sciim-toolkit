# SciIm Toolkit Architecture (Initial)

## App shell
- Single desktop app with tabbed navigation.
- Tabs: Imaging Planner, MA-XRF Corrections, MA-XRF Edit, Registration.

## Core package structure
- `src/sciim_toolkit/app`: entrypoint and main window shell
- `src/sciim_toolkit/models`: project/session models
- `src/sciim_toolkit/services`: IO, settings, and shared app services
- `src/sciim_toolkit/features/*`: feature modules

## Data model strategy
- Project sessions are saved as `.sciim.json` files.
- Relative paths are preferred when possible to improve portability.

## Immediate roadmap
1. Keep Imaging Planner functional and stabilize exports.
2. Migrate MA-XRF correction widget from legacy script into `features/maxrf_corrections`.
3. Add false-colour layer stack and blending engine in `features/maxrf_edit`.
4. Add manual control-point registration, then SimpleITK auto-registration.

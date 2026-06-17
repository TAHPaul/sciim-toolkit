# Building standalone executables

SciIm Toolkit ships as standalone, double-click apps for **macOS** and **Windows** so
colleagues can run it from a shared drive without installing Python or creating a venv.

Builds are produced by [PyInstaller](https://pyinstaller.org/) and assembled in GitHub
Actions. The same spec file (`sciim_toolkit.spec`) drives both the cloud builds and any
local smoke test.

> **Why GitHub Actions?** A Windows `.exe` can only be built on Windows and a macOS
> `.app` only on macOS — there is no cross-compilation. CI runs both, so you never need a
> second machine.

---

## Producing a new build (operator)

Builds are **manual** — they only run when you ask for one. This is the "ship it when
there's enough updates" control.

1. Push your latest changes to `main`.
2. Go to **GitHub → Actions → "Build executables" → Run workflow**.
3. (Optional) set the **version** label — it only affects the release name.
4. Click **Run workflow**. The macOS and Windows jobs run in parallel (~10–20 min).
5. When green, a **prerelease** appears under **Releases** named
   `SciIm Toolkit <version> (build <run number>)` with two attachments:
   - `sciim-toolkit-macos.zip`
   - `sciim-toolkit-windows.zip`

   (The same two zips are also available as **Artifacts** on the workflow run page.)

6. Download both zips and copy them to the shared drive.

---

## Running it (colleagues)

> The builds are **unsigned**, so the OS shows a one-time warning the first time. This is
> expected for an internal tool — the steps below clear it.

1. **Copy the zip off the shared drive to your own machine first**, then unzip and run
   it locally. (Running it directly over the network share loads hundreds of library
   files across the network and is slow/unreliable.)

2. **macOS** (`sciim-toolkit-macos.zip` → `SciIm Toolkit.app`)
   - First launch: **right-click** the app → **Open** → **Open** in the dialog.
     (After the first time, double-click works normally.)
   - If macOS still refuses ("app is damaged"), run once in Terminal:
     `xattr -cr "SciIm Toolkit.app"`
   - On Apple Silicon Macs you may get a one-time prompt to install **Rosetta** — accept it.

3. **Windows** (`sciim-toolkit-windows.zip` → `SciIm Toolkit\` folder)
   - Unzip the whole folder, then run **`SciIm Toolkit.exe`** inside it.
   - If SmartScreen shows "Windows protected your PC": **More info** → **Run anyway**.

---

## Local smoke test (macOS, optional)

Verify a build on your own Mac before relying on CI:

```bash
pip install ".[build]"
pyinstaller --noconfirm sciim_toolkit.spec
open "dist/SciIm Toolkit.app"
```

(On Windows the same `pyinstaller --noconfirm sciim_toolkit.spec` produces
`dist\SciIm Toolkit\SciIm Toolkit.exe`.)

---

## Troubleshooting

- **App opens then immediately quits / "ModuleNotFoundError" in a frozen build.** A
  scientific package wasn't fully collected. Add its top-level import name to the
  `_collect_pkgs` list in `sciim_toolkit.spec` and rebuild.
- **Build is large (~400–800 MB unzipped).** Expected — scipy, scikit-image and OpenCV
  are big. Fine for a shared drive.

---

## Not done yet (possible follow-ups)

- **Code signing / notarization** to remove the macOS/Windows first-launch warnings
  entirely. Requires paid certificates (Apple Developer Program; a Windows code-signing
  certificate).
- **App icon** — currently the default; drop an `.icns`/`.ico` into the repo and
  reference it in `sciim_toolkit.spec`.
- **Native Apple Silicon build** — today we ship one Intel build that runs everywhere via
  Rosetta. A second `macos-14` job could add a native arm64 zip.

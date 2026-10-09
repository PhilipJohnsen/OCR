# Packaging the OCT Report Extractor

Turns the Tkinter GUI ([GUI/gui.py](GUI/gui.py)) into a standalone executable
via PyInstaller, with Tesseract OCR bundled inside so end users don't need to
install it separately.

## One-time setup

```
pip install -r requirements.txt
```

## Building

Build on the actual target OS in each case -- PyInstaller does not
cross-compile (a Windows machine can't produce a Linux binary or vice versa).

**Windows:**
```powershell
scripts\vendor_tesseract_windows.ps1   # only needed once, or after updating Tesseract
scripts\build_windows.ps1
# -> dist\OCTReportExtractor\OCTReportExtractor.exe  (+ its _internal\ folder)
```

**Linux / macOS:**
```bash
scripts/vendor_tesseract_unix.sh   # only needed once, or after updating Tesseract
scripts/build_unix.sh
# -> dist/OCTReportExtractor/OCTReportExtractor  (+ its _internal/ folder)
```

The build is **onedir**, not onefile: `dist/OCTReportExtractor/` is a whole
folder (the `.exe` plus an `_internal/` folder of DLLs/data), not a single
file. Zip the whole folder to hand it to someone else -- see "Deploying to
end-user machines" below.

Both vendor scripts expect Tesseract already installed system-wide on the
build machine (`apt-get install tesseract-ocr`, `brew install tesseract`, or
the [UB-Mannheim Windows installer](https://github.com/UB-Mannheim/tesseract/wiki))
-- they copy that install (binary + its runtime libraries + English language
data) into `vendor/tesseract/<platform>/`, which `oct_extractor.spec` then
bundles into the executable. `vendor/` is gitignored (large, platform-specific
binaries) and gets rebuilt locally by whoever runs the build.

## How it fits together

- **`vision/config/settings.py`** resolves the Tesseract binary at import
  time: it prefers `vendor/tesseract/<platform>/` if present (bundled build),
  falls back to the system PATH / common install locations otherwise
  (running from source on a dev machine). It also sets `TESSDATA_PREFIX` (and
  `LD_LIBRARY_PATH`/`DYLD_LIBRARY_PATH` on Linux/macOS) so the vendored binary
  can find its language data and shared libraries, which aren't in their usual
  system locations once copied next to the binary.
- **`GUI/gui.py`** computes its base directory from `sys._MEIPASS` when frozen
  (`getattr(sys, "frozen", False)`) instead of a path relative to the source
  tree, and never `chdir`s -- a frozen app's working directory isn't something
  to write persistent output into. Input/output folders are chosen by the
  user (Browse buttons); output defaults to landing next to the input images,
  which is guaranteed writable in both source and frozen contexts.
- **`oct_extractor.spec`** bundles `vision/config` and `vision/src` as data
  (plain `.py` files copied into the app, imported at runtime the same way
  `gui.py` already does when run from source) rather than analyzing them as
  part of the frozen import graph -- which is also why `cv2`, `numpy`, and
  `pytesseract` are listed explicitly under `hiddenimports` in the spec: those
  imports live inside the data-only files, invisible to PyInstaller's static
  analysis, and are silently missing from the build without that. The spec
  builds **onedir** (`EXE(..., exclude_binaries=True)` + `COLLECT(...)`)
  rather than onefile, and on Windows attaches `GUI/assets/app.ico` as the
  `.exe` icon and `scripts/version_info.txt` as its version resource (both
  are Windows-only PyInstaller features, skipped on other platforms).

## Deploying to end-user machines

- **Getting it there:** the onedir build is ~210-215MB zipped
  (`dist/OCTReportExtractor-win64.zip` after `Compress-Archive`), too big for
  most email systems -- use an internal file share, USB drive, or internal
  download link. Unzip on the target machine and the whole
  `OCTReportExtractor/` folder is self-contained; nothing else needs
  installing (Tesseract is bundled).
- **First launch will very likely show a SmartScreen prompt** ("Windows
  protected your PC") because the `.exe` is unsigned and unrecognized by
  Microsoft's reputation service. The user needs to click **"More info" →
  "Run anyway"**. On a machine with restrictive Defender/SmartScreen policy
  (common on managed corporate/clinical images), this can be an outright
  block instead of a click-through -- check with IT if so. This goes away
  permanently only with a code-signing certificate (~$100-400/yr) applied to
  the build; not set up here.
- **Some antivirus engines may flag or quarantine it** on first contact --
  PyInstaller-built binaries (bundling a Python interpreter) are a known
  pattern some AV heuristics treat with suspicion, signed or not. If a
  target machine's AV quarantines the `.exe`, you'll need an exclusion from
  IT or to submit the file to that vendor for allowlisting.
- **Prerequisite runtime:** `opencv-python`'s wheel needs the Visual C++
  2015-2022 x64 redistributable (`vcruntime140.dll` /
  `vcruntime140_1.dll`) present on the machine. Most updated Win10/11
  machines already have this via Windows Update, but it isn't guaranteed on
  an older or locked-down image -- if the app fails to launch with a missing
  DLL error, install the redistributable from Microsoft and retry.
- **Architecture:** builds are x64 only. Runs fine under emulation on ARM64
  Windows (Windows on Snapdragon/Copilot+ PCs), just slower than native.

## Known limitations

- **Linux binary portability is bounded by glibc.** `vendor_tesseract_unix.sh`
  deliberately does not bundle `libc`/`libpthread`/etc. (see the script's
  header comment), so a Linux build is portable to machines with an
  equal-or-newer glibc than the build machine, not older ones. Build on the
  oldest distro you need to support, or in a manylinux-style container.
- **Linux/macOS builds are untested** -- there's no Linux/macOS machine in
  this environment to build or run on. The Windows build was fully verified
  (built, launched, driven through a real extraction end-to-end); the Unix
  scripts follow the same approach but should get a real test run on those
  platforms before you rely on them.

# OCT Report Extractor

A desktop program that reads exported Topcon **OCT reports** (image files) and
collects the printed values (ID, RNFL thickness, macula sectors, disc
parameters, image quality) into one CSV, with one row per report.

Each value is read with OCR and gets a confidence score. Uncertain values are
flagged, and you can check them in the built-in **Human Review** window, which
shows the cropped part of the report next to the value read.

- [Part 1: Using the program](#part-1-using-the-program)
- [Part 2: Running from source and compiling](#part-2-running-from-source-and-compiling)

---

# Part 1: Using the program
## Installing

No Python or Tesseract needed. Everything is included.

1. Get **`OCTReportExtractor-win64.zip`** from the **Releases** page or the maintainer.
2. Right-click it → **Extract All...**. Keep the `.exe` and the `_internal`
   folder together. For a desktop icon, right-click the `.exe` →
   **Send to → Desktop (create shortcut)**.
3. Double-click **`OCTReportExtractor.exe`**.

The first time, Windows may say *"Windows protected your PC"* because the
program isn't code-signed. Click **More info → Run anyway**.

Requires Windows 10/11, 64-bit. Works offline and never sends data anywhere.

## Step by step

1. **Input folder**: the folder with the report images.
2. **Output folder** *(optional)*: defaults to the input folder.
3. **Report type**:
   - **GlaucomaHood**: *"3D Wide Glaucoma Report with VF test points"*
   - **GlaucomaReport**: *"3D Wide(H) Glaucoma Report"*
   - *WIP* is a placeholder and does nothing yet.

   Only images whose title matches are processed, so mixed folders are fine.
   Run once per report type.
4. **Search all subfolders** *(optional)*: searches up to 7 levels deep and
   warns about any deeper folders.
5. Click **Run Extraction**. Each report is logged as `ok` or `NEEDS REVIEW`.
   If anything was flagged, you're offered Human Review at the end.

Results go to the output folder: `extracted_data.csv` and `review\<report name>\`
(crops used by Human Review).

> **Each run overwrites `extracted_data.csv`, including any Human Review
> corrections.** Rename or move it, or pick another output folder, first.

## Supported reports and images

- **File types:** `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`
- **Image size:** standard device exports only.
  - *GlaucomaHood*: exactly **1286 × 909** px.
  - *GlaucomaReport*: about **1285 × 908** px. Small margins or offsets are
    aligned automatically. Reports at another resolution are flagged, not read.
- **Filenames:** any name works. If it follows Topcon's pattern
  (`<ID>_<YYYYMMDD>_<HHMMSS>_OCTReport_<L|R>_<n>`), the patient ID and eye are
  checked against the report and mismatches are flagged.

## The output spreadsheet

Every value has its own column plus a `<name> confidence` column (0–100).

- **Patient / scan:** `ID`, `Name`, `Gender`, `DOB`, `Age`, `Capture Date`,
  `Fixation`, `Scantype`, `R/L eye`, `Image quality`, `image_quality_band`
  (green / yellow / red), `low_scan_quality` (`True` if quality < 40).
  On GlaucomaReport, Age is calculated from DOB and Capture Date.
  Dates are `DD/MM/YYYY`.
- **RNFL:** clock-hour sectors (e.g. `RNFL Superior Superior`, `RNFL Nasal Top`),
  named per eye since nasal/temporal mirror between OD and OS; averages
  `RNFL Total Thickness`, `RNFL Superior`, `RNFL Inferior`.
- **GlaucomaReport only:** GCL++/GCL+ sectors (`Superior`, `TemporalTop`,
  `NasalTop`, `TemporalBottom`, `NasalBottom`, `Inferior`) and disc topography
  (`Disc Area`, `Cup Area`, `Rim Area`, `C/D Area Ratio`, `Linear CDR`,
  `Vertical CDR`, `Cup Volume`, `Rim Volume`, `Horizontal D.D`, `Vertical D.D`).

**Quality-control columns:**

| Column | Meaning |
|---|---|
| `avg_confidence` | Average confidence across the report |
| `needs_human_review` | `True` if a field is < 90, the average is < 80, scan quality is low, or the filename doesn't match |
| `human_reviewed` | `True` once all flagged fields were checked in Human Review |
| `filename_patient_id_match` / `filename_eye_match` | Filename check (empty if not Topcon's pattern) |
| `layout_error` | Why a report couldn't be read (e.g. wrong image size) |

## Human Review

Shows each uncertain value: the crop on the left, the field, confidence and
value on the right. Correct the **Value** if needed and press **Enter**
(**Save & Next >**). **< Previous** goes back. **Finish** or **Close** saves and
rewrites the CSV.

- Checked values get confidence 100. When all flagged fields of a report are
  checked, it gets `needs_human_review = False`, `human_reviewed = True`.
- Unfinished reports stay flagged. Continue via **Human Review...** in the main window.
- Correcting DOB or Capture Date recalculates Age.
- Reports flagged with nothing to crop (wrong size, low quality, filename
  mismatch) are logged as *"flagged with no visual crop to review (check
  manually)"*. Check the original image yourself.

## Opening the CSV in Excel or LibreOffice

- **LibreOffice Calc:** use **Comma** as the only separator. Untick **Other**
  if it contains `/`, or dates and `R/L eye` get split.
- **Excel** (Danish/European settings): use **Data → From Text/CSV** with
  **Comma** as the delimiter.

## Troubleshooting

| Problem | What to do |
|---|---|
| "Windows protected your PC" | **More info → Run anyway** (first time only) |
| Won't start / `VCRUNTIME140.dll` error | Install the *Microsoft Visual C++ Redistributable (x64)* |
| Antivirus or IT blocks the `.exe` | Common false alarm for packaged programs. Ask IT to allow it |
| "No images found" | Check the folder, or tick **Search all subfolders** |
| "None of the ... images were classified as ..." | Wrong **Report type** selected |
| `NOT READ -- image is ...x..., expected ...` | Re-export from Topcon at the normal resolution |
| Columns look shifted | See [Opening the CSV](#opening-the-csv-in-excel-or-libreoffice) |
| Anything else | Copy the error from the log and send it to the maintainer |

---

# Part 2: Running from source and compiling

## Requirements

- **Python 3.10+** with Tkinter (on Linux: `python3-tk`)
- **Tesseract OCR 5.x**: Windows via the
  [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki),
  Linux `sudo apt-get install tesseract-ocr`, macOS `brew install tesseract`
- Python packages pinned in [requirements.txt](requirements.txt)

```bash
git clone https://github.com/PhilipJohnsen/dataextract.git
cd dataextract
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Running from source

- **GUI:** `python GUI/gui.py`. The input folder defaults to `vision/reference/`
  (empty in the repo; real exports are git-ignored because their filenames
  carry CPR numbers).
- **Command line** (GlaucomaHood only): `cd vision && python main.py`. Reads
  `vision/reference/`, writes `vision/output/extracted_data.csv` and review crops.

Tesseract is looked up in `vendor/tesseract/<platform>/`, then `PATH`, then
common install locations (see `vision/config/settings.py`).

## Building the Windows program

Build on Windows (PyInstaller doesn't cross-compile). Tesseract is bundled, so
users install nothing.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

This vendors Tesseract into `vendor\` if missing. After upgrading Tesseract, rerun
`scripts\vendor_tesseract_windows.ps1` (add `-SourceDir "D:\path"` if not in
Program Files).

Output: `dist\OCTReportExtractor\` (the `.exe` plus `_internal\`) and
`dist\OCTReportExtractor-win64.zip` (~210 MB, the file to hand out).

- The build is onedir, not a single `.exe`: single-file builds unpack ~500 MB
  to `%TEMP%` on every launch and trigger antivirus more often.
- Icon and version info are applied automatically. `build/`, `dist/` and
  `vendor/` are git-ignored.
- **Test the zip on a clean Windows VM** (no Python/Tesseract) before handing
  it out, to catch VC++ runtime, SmartScreen and antivirus issues.

## Building on Linux / macOS

```bash
scripts/vendor_tesseract_unix.sh   # once, or after upgrading Tesseract
scripts/build_unix.sh              # -> dist/OCTReportExtractor/OCTReportExtractor
```

Linux builds need the same or newer glibc as the build machine. Neither build
has been tested on real machines yet. See [PACKAGING.md](PACKAGING.md) for details.

## Releasing a new version

1. Raise the version in `scripts/version_info.txt`.
2. Build and test the zip on a clean machine.
3. Commit, tag (`git tag v1.0.1 && git push --tags`), and attach the zip to a
   GitHub Release. Don't commit the zip.

## Project layout

```
GUI/
  gui.py                  Tkinter app incl. Human Review window
  assets/app.ico          Windows icon
vision/
  main.py                 CLI batch runner (GlaucomaHood)
  config/
    settings.py           Paths, thresholds, image size, Tesseract lookup
    GlaucomaHood.py       Field pixel boxes (ROIs)
    GlaucomaReport.py     Field pixel boxes + page landmarks
  src/
    discover.py           Image search + report-type detection
    align.py              Aligns GlaucomaReport images on ruled lines
    extract.py            Crop → OCR → validate → confidence → flag
    fields.py             Dates, ages, quality colour band
    sectors.py            RNFL/GCL sectors with OD/OS naming
    ocr.py                Tesseract wrapper + preprocessing
    output.py             CSV writer
  reference/              Default input folder (empty)
scripts/                  Vendoring + build scripts, version resource
oct_extractor.spec        PyInstaller spec
PACKAGING.md              Packaging details
```

## How extraction works

1. **Find** images, optionally in subfolders.
2. **Classify** by OCR of the report title.
3. **Check geometry**: exact size for GlaucomaHood; line-based alignment for
   GlaucomaReport. Misfits get `layout_error`.
4. **Read** each field from a fixed pixel box, upscaled 4×, with Tesseract.
5. **Validate** and range-check (e.g. RNFL 0–350 µm, age 0–120); name sectors by eye.
6. **Flag** low-confidence, low-quality or mismatched reports and save review crops.
7. **Write** the fully quoted CSV.

**Adding a report type:** copy a file in `vision/config/` and measure the pixel
boxes on a standard-resolution export. Register it in `REPORT_CONFIGS`
(`src/extract.py`), add title keywords in `src/discover.py`, and add it to
`REPORT_TYPES` / `IMPLEMENTED_REPORT_TYPES` in `GUI/gui.py`. Verify against
hand-read reference reports.

## Settings

In `vision/config/settings.py`:

| Setting | Default | Effect |
|---|---|---|
| `FIELD_CONFIDENCE_THRESHOLD` | 90 | Field below this is flagged |
| `ROW_CONFIDENCE_THRESHOLD` | 80 | Report average below this is flagged |
| `IMAGE_QUALITY_LOW_THRESHOLD` | 40 | Scan quality below this is flagged |
| `OCR_UPSCALE` | 4 | Crop enlargement before OCR |
| `EXPECTED_IMAGE_SIZE` | (1286, 909) | Required GlaucomaHood size |
| `INPUT_EXTENSIONS` | jpg/jpeg/png/tif/tiff | Accepted image types |

Rebuild after changing these; the packaged app contains a copy of `vision/` from build time.

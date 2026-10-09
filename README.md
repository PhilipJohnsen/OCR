# OCT Report Extractor

A desktop program that reads exported **Topcon OCT glaucoma reports** (image
files) and collects the printed values: patient details, RNFL thickness, GCL
sectors, disc parameters and image quality. It puts them into one spreadsheet
(CSV), with one row per report.

Each value is read with OCR (optical character recognition) and gets a
confidence score. Values the program is unsure of are flagged. You can then
check them one at a time in a built-in **Human Review** window, where the
program shows the cropped part of the report next to the value it read.

> **Important:** This program helps with data entry. It is not a medical
> device. Check the extracted values, especially anything flagged for review,
> before using them for clinical or research decisions.

**Contents**

- [Part 1: Using the program](#part-1-using-the-program)
  - [Installing](#installing)
  - [Step by step](#step-by-step)
  - [Supported reports and images](#supported-reports-and-images)
  - [The output spreadsheet](#the-output-spreadsheet)
  - [Human Review](#human-review)
  - [Opening the CSV in Excel or LibreOffice](#opening-the-csv-in-excel-or-libreoffice)
  - [Troubleshooting](#troubleshooting)
- [Part 2: Running from source and compiling](#part-2-running-from-source-and-compiling)
  - [Requirements](#requirements)
  - [Running from source](#running-from-source)
  - [Building the Windows program](#building-the-windows-program)
  - [Building on Linux / macOS](#building-on-linux--macos)
  - [Releasing a new version](#releasing-a-new-version)
  - [Project layout](#project-layout)
  - [How extraction works](#how-extraction-works)
  - [Settings you may want to change](#settings-you-may-want-to-change)

---

# Part 1: Using the program

## Installing

You **don't** need to install Python or Tesseract. Everything is included.

1. Get **`OCTReportExtractor-win64.zip`**, either from this repository's
   **Releases** page or from the person who maintains the program.
2. Right-click the zip file, choose **Extract All...**, and extract it to a
   folder you can find again, for example `Documents\OCTReportExtractor`.
   - Keep the extracted folder as it is. The program needs the
     `OCTReportExtractor.exe` file **and** the `_internal` folder next to it.
     Don't move the `.exe` out on its own. To get a desktop icon, right-click
     the `.exe` and choose **Send to → Desktop (create shortcut)**.
3. Double-click **`OCTReportExtractor.exe`**.

**The first time you start it**, Windows may show a blue box that says
*"Windows protected your PC"*. The program isn't code-signed, which is why
Windows shows this. Click **More info**, then **Run anyway**. You only need to
do this once.

If your hospital's IT setup blocks the program completely, or the antivirus
removes it, ask IT to allow `OCTReportExtractor.exe`. See also
[Troubleshooting](#troubleshooting).

Requirements: Windows 10 or 11, 64-bit. The program works offline and never
sends data anywhere.

## Step by step

1. **Input folder → Browse...**
   Choose the folder that contains the exported report images.

2. **Output folder → Browse...** *(optional)*
   This is where the results are saved. By default it is the same as the input
   folder. Choose a different folder to keep results apart from the images.

3. **Report type**
   Choose the kind of report you're processing:
   - **GlaucomaHood**: *"3D Wide Glaucoma Report with VF test points"* (Hood report)
   - **GlaucomaReport**: *"3D Wide(H) Glaucoma Report"*
   - *WIP* is a placeholder for a future report type and does nothing yet.

   The program checks the title of every image. Only images that match the
   chosen type are processed, so a folder with mixed report types is fine. Run
   the program once for each report type.

4. **"Search all subfolders..."** *(optional)*
   Tick this if the reports are spread over several folders, for example one
   folder per patient or per month. The program then searches every subfolder,
   up to 7 levels deep. If the folder tree is deeper than that, you get a
   warning that lists the folders that weren't searched.

5. Click **Run Extraction**.
   The progress bar and log show each report as it is processed. Each report
   is marked either `ok` or `NEEDS REVIEW`.

6. When it finishes, the log shows where the spreadsheet was saved. If any
   reports were flagged, the program asks **"Open human review now?"**. See
   [Human Review](#human-review).

### What gets saved

In the output folder:

| File / folder           | Contents                                                                          |
|-------------------------|-----------------------------------------------------------------------------------|
| `extracted_data.csv`    | The spreadsheet, with one row per report                                           |
| `review\<report name>\` | Small cropped images of each uncertain field, used by the Human Review window     |

> **Each run overwrites `extracted_data.csv` in the output folder.** To keep
> the results of an earlier run, rename or move that file before you run
> again, or choose a different output folder.

## Supported reports and images

- **File types:** `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`
- **Report types:** the two Topcon layouts listed above. Other report types
  are skipped. The log shows how many images were skipped and why.
- **Image size matters.** The program knows where each value sits on the page,
  so the images must be standard exports from the device:
  - *GlaucomaHood*: exactly **1286 × 909 pixels**.
  - *GlaucomaReport*: about **1285 × 908 pixels**. A few pixels of extra margin
    or offset (for example a hand-cropped screenshot) is fine, because the
    program lines the page up first. A report saved at a **different zoom /
    resolution** isn't read. It gets flagged with an explanation instead of
    giving wrong numbers.
- **Filenames:** any name works. If a file uses Topcon's standard name pattern
  (`<ID>_<YYYYMMDD>_<HHMMSS>_OCTReport_<L|R>_<n>`), the program also checks
  that the patient ID and eye in the filename match what is printed on the
  report. Any mismatch is flagged.

## The output spreadsheet

Every value has two columns: the value itself (e.g. `RNFL Superior`) and its
OCR confidence (`RNFL Superior confidence`, from 0 to 100).

**Patient / scan columns:** `ID`, `Name`, `Gender`, `DOB`, `Age`, `Capture Date`,
`Fixation`, `Scantype`, `R/L eye`, `Image quality`, plus:

- `image_quality_band`: the colour of Topcon's quality box (green / yellow / red).
- `low_scan_quality`: `True` if the scan quality score is below 40.

On GlaucomaReport, **Age is calculated** from DOB and Capture Date. It isn't
read from the page. Dates are written as `DD/MM/YYYY`.

**Measurement columns**, named after the anatomical sector:

- *RNFL clock-hour sectors*, e.g. `RNFL Superior Superior`, `RNFL Nasal Top`,
  `RNFL Inferior Temporal`, etc. The program uses the eye (OD/OS) to name each
  sector correctly, since nasal and temporal are mirrored between the two eyes.
- *RNFL averages:* `RNFL Total Thickness`, `RNFL Superior`, `RNFL Inferior`
- *GCL++ / GCL+ sectors* (GlaucomaReport): `Superior`, `TemporalTop`,
  `NasalTop`, `TemporalBottom`, `NasalBottom`, `Inferior`
- *Disc topography* (GlaucomaReport): `Disc Area`, `Cup Area`, `Rim Area`,
  `C/D Area Ratio`, `Linear CDR`, `Vertical CDR`, `Cup Volume`, `Rim Volume`,
  `Horizontal D.D`, `Vertical D.D`

**Quality-control columns:**

| Column                                       | Meaning                                                                                                        |
|----------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| `avg_confidence`                             | Average confidence across all fields of the report                                                            |
| `needs_human_review`                         | `True` if any field is below 90 confidence, the average is below 80, scan quality is low, or the filename doesn't match |
| `human_reviewed`                             | `True` once every flagged field of that report was checked in the Human Review window                         |
| `filename_patient_id_match` / `filename_eye_match` | Filename check (empty if the filename doesn't follow Topcon's pattern)                                     |
| `layout_error`                               | Only present when a report couldn't be read at all, e.g. wrong image size. It says why.                        |

## Human Review

The Human Review window goes through **each uncertain value**, one at a time:

- **Left:** the cropped piece of the original report.
- **Right:** the field name, its confidence, and the value the program read.

For each one:

1. Compare the value with the image.
2. Correct it in the **Value** box if it's wrong, or leave it as it is if it's right.
3. Press **Enter** or click **Save & Next >**.

Use **< Previous** to go back. Click **Finish** (on the last item) or **Close**
at any time to save. The CSV is rewritten straight away.

- A value you confirmed or corrected gets a confidence of 100.
- Once **all** flagged fields of a report are checked, that report gets
  `needs_human_review = False` and `human_reviewed = True`.
- If you close early, the reports you haven't finished stay flagged. Click
  **Human Review...** in the main window to carry on.
- If you correct a DOB or Capture Date, Age is recalculated automatically.

Some reports are flagged without anything to look at, for example because the
image size was wrong, scan quality was low, or the filename didn't match. The
log lists these as *"flagged with no visual crop to review (check manually)"*.
Open the original image and check those reports yourself.

> Corrections from Human Review are only kept in `extracted_data.csv`. If you
> run the extraction again on the same output folder, the file is overwritten
> and the corrections are lost. Keep a copy of the reviewed CSV.

## Opening the CSV in Excel or LibreOffice

- **LibreOffice Calc:** in the import dialog, choose **Comma** as the only
  separator. If **Other** is ticked with a `/` in it (LibreOffice remembers
  this from earlier imports), turn it off. Otherwise dates and fields like
  `R/L eye` may still be split.
- **Excel** (Danish / European regional settings): Excel may expect `;` and
  put everything in one column. Use **Data → From Text/CSV** and choose
  **Comma** as the delimiter.

## Troubleshooting

| Problem                                              | What to do                                                                                                                       |
|------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------|
| "Windows protected your PC"                          | Click **More info → Run anyway** (only needed the first time).                                                                    |
| The program won't start / error about `VCRUNTIME140.dll` | Install the *Microsoft Visual C++ Redistributable (x64)* from Microsoft's website, then try again.                           |
| The antivirus removes or blocks the `.exe`           | This is a false alarm that is common for this kind of packaged program. Ask IT to allow it.                                       |
| "No images found"                                    | Check the folder. If the images are in subfolders, tick **Search all subfolders**.                                                |
| "None of the ... images were classified as ..."      | The wrong **Report type** is probably selected. Pick the other type.                                                             |
| A report shows `NOT READ -- image is ...x..., expected ...` | The image wasn't exported at the standard size. Re-export it from the Topcon software at the normal resolution.         |
| Columns look shifted in the spreadsheet             | See [Opening the CSV](#opening-the-csv-in-excel-or-libreoffice).                                                                   |
| Something else went wrong                            | The log window shows the full error. Copy it and send it to the maintainer.                                                      |

---

# Part 2: Running from source and compiling

This part is for whoever maintains or builds the program.

## Requirements

- **Python 3.10 or newer**, including Tkinter. Tkinter comes with the
  python.org Windows installer. On Linux, install `python3-tk`.
- **Tesseract OCR 5.x**:
  - Windows: the [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki)
    (default location `C:\Program Files\Tesseract-OCR`)
  - Linux: `sudo apt-get install tesseract-ocr`
  - macOS: `brew install tesseract`
- Python packages, pinned in [requirements.txt](requirements.txt): OpenCV,
  NumPy, pandas, pytesseract, Pillow, PyInstaller.

```bash
git clone https://github.com/PhilipJohnsen/dataextract.git
cd dataextract
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

## Running from source

**GUI** (same as the packaged program):

```bash
python GUI/gui.py
```

When running from source, the input folder defaults to `vision/reference/`.
Put your exported reports there (it ships empty; real Topcon exports are
git-ignored because their filenames carry the patient's CPR number).

**Command line** (GlaucomaHood only). This processes every image in
`vision/reference/` and writes `vision/output/extracted_data.csv` plus review
crops in `vision/output/review/`:

```bash
cd vision
python main.py
```

Tesseract is located automatically (see `vision/config/settings.py`), in this
order:

1. `vendor/tesseract/<platform>/` (the bundled copy, see below)
2. `tesseract` on `PATH`
3. Common install locations (`C:\Program Files\Tesseract-OCR\`,
   `/usr/bin`, `/usr/local/bin`, `/opt/homebrew/bin`)

## Building the Windows program

The build uses **PyInstaller** with Tesseract bundled inside, so end users
install nothing. Build on Windows. PyInstaller doesn't cross-compile.

```powershell
# 1. Once, or after upgrading Tesseract: copy your Tesseract install into vendor\
powershell -ExecutionPolicy Bypass -File scripts\vendor_tesseract_windows.ps1
#    (use -SourceDir "D:\path\to\Tesseract-OCR" if it's not in Program Files)

# 2. Build and zip
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

`build_windows.ps1` runs step 1 automatically if `vendor\` is missing.

Output:

```
dist\OCTReportExtractor\OCTReportExtractor.exe    <- the program
dist\OCTReportExtractor\_internal\                <- its libraries (must stay next to the .exe)
dist\OCTReportExtractor-win64.zip                 <- the file to hand out (~210 MB)
```

Notes:

- The build is **onedir** (a folder), not a single `.exe`. A single-file
  build unpacks ~500 MB to `%TEMP%` on every launch and triggers antivirus
  more often.
- The icon (`GUI/assets/app.ico`) and the version shown in the file's
  Properties (`scripts/version_info.txt`) are applied automatically.
- `build/`, `dist/` and `vendor/` are gitignored and are recreated locally.
- **Before handing out a build,** test the zip on a clean Windows 10/11
  machine or VM (no Python, no Tesseract). This shows up a missing VC++
  runtime, SmartScreen or antivirus problems that a developer machine hides.

## Building on Linux / macOS

```bash
scripts/vendor_tesseract_unix.sh   # once, or after upgrading Tesseract
scripts/build_unix.sh
# -> dist/OCTReportExtractor/OCTReportExtractor
```

Linux builds only run on machines with the **same or newer glibc** as the
build machine. Build on the oldest distro you need to support. The Linux and
macOS builds haven't been tested on real machines yet.

See [PACKAGING.md](PACKAGING.md) for the full reasoning behind the packaging
setup (hidden imports, data bundling, Tesseract library paths, deployment
caveats).

## Releasing a new version

1. Raise the version in `scripts/version_info.txt` (`filevers`, `prodvers`,
   `FileVersion`, `ProductVersion`).
2. Run `scripts\build_windows.ps1`.
3. Test `dist\OCTReportExtractor-win64.zip` on a clean machine.
4. Commit, tag (`git tag v1.0.1 && git push --tags`), and attach the zip to a
   **GitHub Release** for that tag. Don't commit the zip itself.

## Project layout

```
GUI/
  gui.py                  Tkinter app: folder pickers, run, progress log, Human Review window
  assets/app.ico          Windows icon
vision/
  main.py                 Command-line batch runner (GlaucomaHood)
  config/
    settings.py           Paths, confidence thresholds, expected image size, Tesseract lookup
    GlaucomaHood.py       Pixel boxes (ROIs) for every field on the Hood report
    GlaucomaReport.py     Pixel boxes + page landmarks for the 3D Wide(H) Glaucoma Report
  src/
    discover.py           Recursive image search + report-type detection from the title
    align.py              Shifts GlaucomaReport images onto the reference page using its ruled lines
    extract.py            Per-report pipeline: crop → OCR → validate → confidence → review flag
    fields.py             Field parsing (dates, ages, image-quality colour band)
    sectors.py            RNFL/GCL sector reading and OD/OS-aware naming
    ocr.py                Tesseract wrapper + image preprocessing
    output.py             CSV writer (fully quoted)
  reference/              Default input folder (empty in the repo)
scripts/                  Tesseract vendoring + build scripts, Windows version resource
oct_extractor.spec        PyInstaller spec
PACKAGING.md              Packaging/deployment details
```

## How extraction works

1. **Find**: list images in the folder, or crawl subfolders (`src/discover.py`).
2. **Classify**: OCR the report title and keep only images of the chosen type.
3. **Check geometry**: GlaucomaHood must match 1286×909 exactly. GlaucomaReport
   is aligned on its horizontal ruled lines first (`src/align.py`). Anything
   that doesn't fit is flagged with `layout_error` and isn't read.
4. **Read fields**: each field is cropped from a fixed pixel box (the ROI in
   `vision/config/`), upscaled 4×, and run through Tesseract. RNFL/GCL numbers
   are each read from a tight box of their own.
5. **Validate**: values are parsed (dates, numbers) and range-checked (e.g.
   RNFL 0–350 µm, age 0–120). Sector names are assigned according to the eye
   (OD/OS).
6. **Flag**: a field under 90 confidence, a report average under 80, image
   quality under 40, or a filename mismatch sets `needs_human_review`. Crops
   of the uncertain fields are saved to `review/<report>/` for the GUI.
7. **Write** the fully quoted CSV (`src/output.py`).

**Adding or recalibrating a report type:** copy one of the files in
`vision/config/` and measure the pixel boxes against a reference export at
the device's standard resolution. Register it in `REPORT_CONFIGS` in
`src/extract.py`, add title keywords in `src/discover.py`, and add it to
`REPORT_TYPES` / `IMPLEMENTED_REPORT_TYPES` in `GUI/gui.py`. Check the result
against reference reports whose values you have read by hand.

## Settings you may want to change

All of these are in `vision/config/settings.py`:

| Setting                       | Default      | Effect                                                    |
|-------------------------------|--------------|-----------------------------------------------------------|
| `FIELD_CONFIDENCE_THRESHOLD`  | 90           | A single field below this is flagged                      |
| `ROW_CONFIDENCE_THRESHOLD`    | 80           | A report whose average is below this is flagged           |
| `IMAGE_QUALITY_LOW_THRESHOLD` | 40           | Topcon scan quality below this is flagged                 |
| `OCR_UPSCALE`                 | 4            | Crop enlargement before OCR (4x tested best)                 |
| `EXPECTED_IMAGE_SIZE`         | (1286, 909)  | Required size for GlaucomaHood                            |
| `INPUT_EXTENSIONS`            | jpg/jpeg/png/tif/tiff | Which files count as images                      |

Rebuild the Windows program after changing any of these. The packaged app
includes a copy of `vision/` from the time it was built.

"""Tkinter GUI for batch-running the OCT report extraction pipeline (vision/)."""
import queue
import sys
import threading
import traceback
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# A frozen PyInstaller build (see GUI/oct_extractor.spec) has no "sibling vision/
# folder on disk" -- sys._MEIPASS is the bundle's extraction root (onefile) / dist
# folder (onedir), and vision/ is placed there via --add-data. Running from source,
# it's just the sibling folder next to this file. Either way, nothing here relies
# on the current working directory -- a frozen app's cwd isn't writable/persistent,
# so every path used below is made absolute up front instead of chdir'ing into it.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
VISION_DIR = BASE_DIR / "vision"
sys.path.insert(0, str(VISION_DIR))

from config import settings  # noqa: E402
from src import discover, fields  # noqa: E402
from src.extract import extract_report  # noqa: E402
from src.output import write_rows_csv  # noqa: E402

try:
    from PIL import Image, ImageTk
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

# Every column in output/review/<stem>/ is named exactly after the CSV
# column it backs, except where two columns share one crop ("/" isn't a
# valid filename character, so "R/L eye" and "C/D Area Ratio" are saved as
# "R-L eye.png" / "C-D Area Ratio.png" -- see src/extract.py's _write_named_field).
CROP_TO_COLUMNS = {
    "R-L eye": ["R/L eye"],
    "C-D Area Ratio": ["C/D Area Ratio"],
}

REVIEW_IMAGE_MAX_DIM = 240

# Every report type's per-field confidence column is "<Field> confidence",
# rolled up into a single "avg_confidence" column (see src/extract.py).
CONFIDENCE_SUFFIX = " confidence"
OVERALL_CONFIDENCE_COLUMN = "avg_confidence"


def _confidence_column(column: str) -> str:
    return f"{column}{CONFIDENCE_SUFFIX}"

# Report types selectable in the GUI. "WIP" is a placeholder for a layout
# that's still being calibrated -- it's listed so the dropdown already shows
# where it will go, but selecting it refuses to run until real ROIs land in
# vision/config/.
REPORT_TYPES = ["GlaucomaHood", "GlaucomaReport", "WIP"]
IMPLEMENTED_REPORT_TYPES = {"GlaucomaHood", "GlaucomaReport"}


# GlaucomaReport's DD/MM/YYYY date columns. Its Age isn't OCR'd -- it's
# derived from these two (see vision/src/extract.py) -- so a reviewer edit to
# either one re-derives Age too.
DATE_COLUMNS = ("DOB", "Capture Date")


def _apply_reviewed_date(row: dict, column: str):
    """Normalize a reviewed date to DD/MM/YYYY (a reviewer may type 20/3/1986
    or 20.03.1986) and re-derive Age from DOB + Capture Date. An entry that
    isn't a real date is kept as typed, and Age is blanked -- no age can be
    derived from it."""
    parsed = fields.parse_date(row[column])
    if parsed:
        row[column] = fields.format_date(parsed)
    dob = fields.parse_date(row.get("DOB", ""))
    captured = fields.parse_date(row.get("Capture Date", ""))
    if dob and captured:
        row["Age"] = str(fields.age_on(dob, captured))
        row[_confidence_column("Age")] = min(
            row.get(_confidence_column("DOB"), 0.0), row.get(_confidence_column("Capture Date"), 0.0)
        )
    else:
        row["Age"] = ""
        row[_confidence_column("Age")] = 0.0


class ReviewItem:
    def __init__(self, row_index: int, source_file: str, column: str, crop_path: Path):
        self.row_index = row_index
        self.source_file = source_file
        self.column = column
        self.crop_path = crop_path


class ExtractionGUI(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=12)
        self.master = master
        self.master.title("OCT Report Extractor")
        self.master.geometry("700x520")
        self.master.minsize(560, 400)

        self.grid(row=0, column=0, sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)

        if getattr(sys, "frozen", False):
            # vision/reference/ is dev-only sample data and isn't bundled into a
            # packaged build, so settings.INPUT_DIR wouldn't resolve to anything
            # real here -- start the picker somewhere that actually exists.
            self.input_dir = Path.home()
        else:
            default_input = Path(settings.INPUT_DIR)
            self.input_dir = default_input if default_input.is_absolute() else VISION_DIR / default_input
        # Output defaults to landing right next to the input images -- that's the
        # one location guaranteed to be user-writable whether running from source
        # or from a frozen build, and it's the obvious place to look for results.
        # A user can still point it elsewhere via its own Browse button.
        self.output_dir = self.input_dir
        self._output_dir_overridden = False
        self.output_csv = self.output_dir / "extracted_data.csv"
        self.review_dir = self.output_dir / "review"

        self.input_dir_var = tk.StringVar(value=str(self.input_dir))
        self.output_dir_var = tk.StringVar(value=str(self.output_dir))
        self.output_csv_display_var = tk.StringVar(value=f"Output CSV: {self.output_csv}")
        self.status_var = tk.StringVar(value="Ready.")
        self.report_type_var = tk.StringVar(value=REPORT_TYPES[0])
        self.crawl_subfolders_var = tk.BooleanVar(value=False)

        self._msg_queue: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self.last_rows: list[dict] | None = None

        # review-session state (populated by _open_review_window)
        self._review_items: list[ReviewItem] = []
        self._review_index = 0
        self._review_row_totals: dict[int, int] = {}
        self._review_row_visited: dict[int, set] = {}
        self._review_photo = None  # keep a reference so tkinter doesn't GC it
        self._review_win: tk.Toplevel | None = None

        self._build_widgets()
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------ UI --
    def _build_widgets(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        folder_frame = ttk.Frame(self)
        folder_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        folder_frame.columnconfigure(1, weight=1)

        ttk.Label(folder_frame, text="Input folder:").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(folder_frame, textvariable=self.input_dir_var, state="readonly")
        entry.grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(folder_frame, text="Browse...", command=self._browse_input_dir).grid(row=0, column=2)

        ttk.Label(folder_frame, text="Output folder:").grid(row=1, column=0, sticky="w", pady=(4, 0))
        output_entry = ttk.Entry(folder_frame, textvariable=self.output_dir_var, state="readonly")
        output_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=(4, 0))
        ttk.Button(folder_frame, text="Browse...", command=self._browse_output_dir).grid(
            row=1, column=2, pady=(4, 0)
        )

        ttk.Label(folder_frame, text="Report type:").grid(row=2, column=0, sticky="w", pady=(4, 0))
        self.report_type_combo = ttk.Combobox(
            folder_frame,
            textvariable=self.report_type_var,
            values=REPORT_TYPES,
            state="readonly",
        )
        self.report_type_combo.grid(row=2, column=1, sticky="w", padx=6, pady=(4, 0))

        self.crawl_check = ttk.Checkbutton(
            folder_frame,
            text=f"Search all subfolders (up to {discover.MAX_CRAWL_DEPTH} levels deep) "
            "and keep only images matching the report type above",
            variable=self.crawl_subfolders_var,
        )
        self.crawl_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        run_frame = ttk.Frame(self)
        run_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        run_frame.columnconfigure(1, weight=1)

        self.run_button = ttk.Button(run_frame, text="Run Extraction", command=self._start_extraction)
        self.run_button.grid(row=0, column=0)
        self.progress = ttk.Progressbar(run_frame, mode="determinate")
        self.progress.grid(row=0, column=1, sticky="ew", padx=8)
        self.review_button = ttk.Button(
            run_frame, text="Human Review...", command=self._open_review_window, state="disabled"
        )
        self.review_button.grid(row=0, column=2)

        ttk.Label(self, textvariable=self.status_var).grid(row=2, column=0, sticky="w", pady=(0, 4))

        self.log_text = ScrolledText(self, height=18, state="normal", wrap="word", font=("Consolas", 9))
        self.log_text.grid(row=3, column=0, sticky="nsew")

        footer = ttk.Frame(self)
        footer.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        ttk.Label(footer, textvariable=self.output_csv_display_var).pack(side="left")

    def _browse_input_dir(self):
        chosen = filedialog.askdirectory(
            initialdir=str(self.input_dir if self.input_dir.is_dir() else Path.home())
        )
        if chosen:
            self.input_dir = Path(chosen)
            self.input_dir_var.set(str(self.input_dir))
            if not self._output_dir_overridden:
                self._set_output_dir(self.input_dir)

    def _browse_output_dir(self):
        chosen = filedialog.askdirectory(
            initialdir=str(self.output_dir if self.output_dir.is_dir() else Path.home())
        )
        if chosen:
            self._output_dir_overridden = True
            self._set_output_dir(Path(chosen))

    def _set_output_dir(self, path: Path):
        self.output_dir = path
        self.output_dir_var.set(str(self.output_dir))
        self.output_csv = self.output_dir / "extracted_data.csv"
        self.review_dir = self.output_dir / "review"
        self.output_csv_display_var.set(f"Output CSV: {self.output_csv}")

    # ------------------------------------------------------------ extraction --
    def _start_extraction(self):
        if self._worker and self._worker.is_alive():
            return
        report_type = self.report_type_var.get()
        if report_type not in IMPLEMENTED_REPORT_TYPES:
            messagebox.showinfo(
                "Not yet available", f"The '{report_type}' report type isn't implemented yet."
            )
            return
        if not self.input_dir.is_dir():
            messagebox.showerror("Folder not found", f"{self.input_dir} does not exist.")
            return

        self.run_button.state(["disabled"])
        self.review_button.state(["disabled"])
        self.report_type_combo.state(["disabled"])
        self.crawl_check.state(["disabled"])
        self.log_text.delete("1.0", tk.END)
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.status_var.set("Starting...")

        # extract_report() saves flagged-field crops via settings.REVIEW_DIR, a
        # module-level path it doesn't take as an argument -- point it at this
        # run's chosen output folder before kicking off the worker.
        settings.REVIEW_DIR = str(self.review_dir)

        crawl_subfolders = self.crawl_subfolders_var.get()
        self._worker = threading.Thread(
            target=self._run_pipeline, args=(report_type, crawl_subfolders), daemon=True
        )
        self._worker.start()

    def _run_pipeline(self, report_type: str, crawl_subfolders: bool):
        """Worker-thread entry point: resolve the candidate image list (either
        a flat folder listing or a recursive crawl), classify every candidate
        by report layout, and keep only the ones matching `report_type` --
        a folder can (and in practice does) hold a mix of layouts, and
        feeding the wrong layout's ROIs to extract_report() just produces
        garbage OCR output instead of an error. Runs off the UI thread, so
        every status/log update goes through the queue.

        Any exception is reported back as an "error" message -- an uncaught
        one would end this thread silently and leave the UI waiting forever,
        Run button disabled."""
        try:
            self._run_pipeline_steps(report_type, crawl_subfolders)
        except Exception as exc:  # noqa: BLE001 -- surface anything, don't hang
            self._msg_queue.put(("error", f"{type(exc).__name__}: {exc}", traceback.format_exc()))

    def _run_pipeline_steps(self, report_type: str, crawl_subfolders: bool):
        if crawl_subfolders:
            candidates = self._crawl_for_candidates()
            if candidates is None:
                return  # a "no_images" message was already queued
        else:
            candidates = sorted(
                p for p in self.input_dir.iterdir() if p.suffix.lower() in settings.INPUT_EXTENSIONS
            )
            if not candidates:
                self._msg_queue.put(("no_images", f"No images found in {self.input_dir}"))
                return

        image_paths = self._classify_candidates(candidates, report_type)
        if image_paths is None:
            return  # a "no_images" message was already queued
        self._run_extraction(image_paths, report_type)

    def _crawl_for_candidates(self) -> list[Path] | None:
        """Recursively finds every image anywhere below self.input_dir --
        folder names and nesting depth aren't assumed, see src/discover.py."""
        self._msg_queue.put(("log", f"Scanning {self.input_dir} for images (up to {discover.MAX_CRAWL_DEPTH} folder levels deep)..."))
        candidates, truncated_dirs = discover.find_candidate_images(self.input_dir, exclude_dirs=(self.review_dir,))
        if truncated_dirs:
            # Loud, not just a log line: a truncated branch means the result
            # below may be missing images the user expected included.
            listed = "\n".join(str(d) for d in truncated_dirs[:10])
            more = f"\n...and {len(truncated_dirs) - 10} more" if len(truncated_dirs) > 10 else ""
            self._msg_queue.put((
                "warn",
                "Folder tree too deep",
                f"Stopped descending {discover.MAX_CRAWL_DEPTH} folder levels below {self.input_dir} -- "
                f"these {len(truncated_dirs)} folder(s) still had subfolders left unexplored, "
                f"so results may be incomplete:\n\n{listed}{more}",
            ))
        if not candidates:
            self._msg_queue.put(
                ("no_images", f"No images found anywhere under {self.input_dir}")
            )
            return None
        return candidates

    def _classify_candidates(self, candidates: list[Path], report_type: str) -> list[Path] | None:
        """Classifies each candidate by report layout (see src/discover.py)
        and keeps only the ones matching `report_type`."""
        self._msg_queue.put(("log", f"Found {len(candidates)} candidate image(s). Classifying by report type..."))
        self._msg_queue.put(("scan_start", len(candidates)))
        matched: list[Path] = []
        skipped_reasons: dict[str, int] = {}
        for i, path in enumerate(candidates, 1):
            detected = discover.detect_report_type(path)
            if detected == report_type:
                matched.append(path)
            else:
                reason = detected or "undetected"
                skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
            self._msg_queue.put(("scan_progress", i, len(candidates)))

        if skipped_reasons:
            breakdown = ", ".join(f"{count} {reason}" for reason, count in sorted(skipped_reasons.items()))
            self._msg_queue.put(("log", f"Skipped {sum(skipped_reasons.values())} non-matching image(s): {breakdown}"))

        if not matched:
            self._msg_queue.put((
                "no_images",
                f"None of the {len(candidates)} candidate image(s) under {self.input_dir} "
                f"were classified as '{report_type}'.",
            ))
            return None

        self._msg_queue.put(("log", f"{len(matched)} '{report_type}' image(s) queued for extraction.\n"))
        return matched

    def _run_extraction(self, image_paths: list[Path], report_type: str):
        rows = []
        flagged = 0
        start = time.time()
        self._msg_queue.put(("extract_start", len(image_paths)))
        for i, path in enumerate(image_paths, 1):
            row = extract_report(path, report_type=report_type)
            row.setdefault("human_reviewed", False)
            rows.append(row)
            if row.get("needs_human_review"):
                flagged += 1
            self._msg_queue.put(("progress", i, len(image_paths), path.name, row))

        self._write_rows_to_csv(rows)
        elapsed = time.time() - start
        self._msg_queue.put(("done", rows, flagged, elapsed))

    def _write_rows_to_csv(self, rows: list[dict]):
        write_rows_csv(rows, self.output_csv)

    def _poll_queue(self):
        try:
            while True:
                msg = self._msg_queue.get_nowait()
                if msg[0] == "log":
                    self._log(msg[1])
                elif msg[0] == "warn":
                    _, title, text = msg
                    self._log(f"WARNING: {title} -- {text}")
                    messagebox.showwarning(title, text)
                elif msg[0] == "scan_start":
                    total = msg[1]
                    self.progress["maximum"] = total
                    self.progress["value"] = 0
                    self.status_var.set(f"Classifying 0/{total}...")
                elif msg[0] == "scan_progress":
                    _, i, total = msg
                    self.progress["value"] = i
                    self.status_var.set(f"Classifying {i}/{total}...")
                elif msg[0] == "extract_start":
                    total = msg[1]
                    self.progress["maximum"] = max(total, 1)
                    self.progress["value"] = 0
                    self.status_var.set(f"Processing 0/{total}...")
                elif msg[0] == "progress":
                    _, i, total, name, row = msg
                    self.progress["value"] = i
                    status = "NEEDS REVIEW" if row.get("needs_human_review") else "ok"
                    conf = row.get(OVERALL_CONFIDENCE_COLUMN)
                    if row.get("layout_error"):
                        # Never OCR'd at all -- say why instead of "avg_confidence=None".
                        self._log(f"[{i}/{total}] {name}: NOT READ -- {row['layout_error']}")
                    else:
                        self._log(f"[{i}/{total}] {name}: {OVERALL_CONFIDENCE_COLUMN}={conf} ({status})")
                    self.status_var.set(f"Processing {i}/{total}...")
                elif msg[0] == "error":
                    _, summary, trace = msg
                    self._log(f"\nERROR -- extraction stopped:\n{trace}")
                    messagebox.showerror("Extraction failed", f"Extraction stopped with an error:\n\n{summary}")
                    self.status_var.set("Failed -- see log.")
                    self.run_button.state(["!disabled"])
                    self.report_type_combo.state(["!disabled"])
                    self.crawl_check.state(["!disabled"])
                elif msg[0] == "no_images":
                    self._log(msg[1])
                    messagebox.showwarning("No images", msg[1])
                    self.status_var.set("Ready.")
                    self.run_button.state(["!disabled"])
                    self.report_type_combo.state(["!disabled"])
                    self.crawl_check.state(["!disabled"])
                elif msg[0] == "done":
                    _, rows, flagged, elapsed = msg
                    self.last_rows = rows
                    self._log(f"\nWrote {len(rows)} rows to {self.output_csv} in {elapsed:.1f}s")
                    self._log(f"Flagged for human review: {flagged}/{len(rows)}")
                    self.status_var.set(f"Done. {len(rows)} report(s) processed, {flagged} flagged for review.")
                    self.run_button.state(["!disabled"])
                    self.report_type_combo.state(["!disabled"])
                    self.crawl_check.state(["!disabled"])
                    if flagged:
                        self.review_button.state(["!disabled"])
                        if messagebox.askyesno(
                            "Human review",
                            f"{flagged} report(s) were flagged for review.\nOpen human review now?",
                        ):
                            self._open_review_window()
                    else:
                        self.review_button.state(["disabled"])
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _log(self, text: str):
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)

    # ----------------------------------------------------------- human review --
    def _build_review_items(self) -> list[ReviewItem]:
        items: list[ReviewItem] = []
        no_crop_rows: list[str] = []
        for row_index, row in enumerate(self.last_rows or []):
            if not row.get("needs_human_review"):
                continue
            stem = Path(row["source_file"]).stem
            crop_dir = self.review_dir / stem
            crops = sorted(crop_dir.glob("*.png")) if crop_dir.is_dir() else []
            if not crops:
                no_crop_rows.append(row["source_file"])
                continue
            for crop_path in crops:
                key = crop_path.stem
                for column in CROP_TO_COLUMNS.get(key, [key]):
                    if column in row:
                        items.append(ReviewItem(row_index, row["source_file"], column, crop_path))
        if no_crop_rows:
            self._log(
                "Note: flagged with no visual crop to review (check manually): "
                + ", ".join(no_crop_rows)
            )
        return items

    def _open_review_window(self):
        if not self.last_rows:
            return
        if self._review_win and tk.Toplevel.winfo_exists(self._review_win):
            self._review_win.lift()
            return

        items = self._build_review_items()
        if not items:
            messagebox.showinfo("Human review", "No reviewable fields with a saved crop were found.")
            return

        self._review_items = items
        self._review_index = 0
        self._review_row_totals = {}
        for item in items:
            self._review_row_totals[item.row_index] = self._review_row_totals.get(item.row_index, 0) + 1
        self._review_row_visited = {row_idx: set() for row_idx in self._review_row_totals}

        self.run_button.state(["disabled"])

        win = tk.Toplevel(self.master)
        self._review_win = win
        win.title("Human Review")
        win.geometry("780x440")
        win.minsize(640, 380)
        win.protocol("WM_DELETE_WINDOW", self._on_review_close)

        win.columnconfigure(0, weight=0)
        win.columnconfigure(1, weight=1)
        win.rowconfigure(1, weight=1)

        self.review_progress_var = tk.StringVar()
        ttk.Label(win, textvariable=self.review_progress_var, font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4)
        )

        image_frame = ttk.Frame(win, relief="groove", borderwidth=1)
        image_frame.grid(row=1, column=0, sticky="ns", padx=(12, 6), pady=6)
        self.review_image_label = ttk.Label(image_frame)
        self.review_image_label.pack(padx=10, pady=10)

        detail_frame = ttk.Frame(win)
        detail_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 12), pady=6)
        detail_frame.columnconfigure(1, weight=1)

        ttk.Label(detail_frame, text="Source file:").grid(row=0, column=0, sticky="w", pady=2)
        self.review_source_var = tk.StringVar()
        ttk.Label(detail_frame, textvariable=self.review_source_var).grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(detail_frame, text="Field:").grid(row=1, column=0, sticky="w", pady=2)
        self.review_field_var = tk.StringVar()
        ttk.Label(detail_frame, textvariable=self.review_field_var, font=("Consolas", 10, "bold")).grid(
            row=1, column=1, sticky="w", pady=2
        )

        ttk.Label(detail_frame, text="Confidence:").grid(row=2, column=0, sticky="w", pady=2)
        self.review_conf_var = tk.StringVar()
        ttk.Label(detail_frame, textvariable=self.review_conf_var).grid(row=2, column=1, sticky="w", pady=2)

        ttk.Label(detail_frame, text="Value:").grid(row=3, column=0, sticky="nw", pady=(10, 2))
        self.review_value_var = tk.StringVar()
        value_entry = ttk.Entry(detail_frame, textvariable=self.review_value_var, font=("Consolas", 11))
        value_entry.grid(row=3, column=1, sticky="ew", pady=(10, 2))
        value_entry.bind("<Return>", lambda _e: self._review_next())
        self.review_value_entry = value_entry

        ttk.Label(
            detail_frame,
            text="Confirming or editing sets this field's confidence to 100 and,\n"
            "once every flagged field for this report is reviewed, clears its review flag.",
            foreground="#666666",
            wraplength=340,
            justify="left",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        button_frame = ttk.Frame(win)
        button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 12))
        ttk.Button(button_frame, text="< Previous", command=self._review_prev).pack(side="left")
        self.review_next_button = ttk.Button(button_frame, text="Save & Next >", command=self._review_next)
        self.review_next_button.pack(side="left", padx=6)
        ttk.Button(button_frame, text="Close", command=self._on_review_close).pack(side="right")

        self._render_review_item()
        value_entry.focus_set()

    def _render_review_item(self):
        item = self._review_items[self._review_index]
        row = self.last_rows[item.row_index]
        total = len(self._review_items)

        self.review_progress_var.set(f"Reviewing item {self._review_index + 1} of {total}")
        self.review_source_var.set(item.source_file)
        self.review_field_var.set(item.column)
        conf = row.get(_confidence_column(item.column))
        self.review_conf_var.set(f"{conf}" if conf is not None else "n/a")
        self.review_value_var.set(str(row.get(item.column, "")))

        self._review_photo = self._load_crop_photo(item.crop_path)
        self.review_image_label.configure(image=self._review_photo)

        is_last = self._review_index == total - 1
        self.review_next_button.configure(text="Finish" if is_last else "Save & Next >")

    def _load_crop_photo(self, path: Path):
        if _PIL_AVAILABLE:
            img = Image.open(path)
            w, h = img.size
            scale = max(1, REVIEW_IMAGE_MAX_DIM // max(w, h))
            if scale > 1:
                img = img.resize((w * scale, h * scale), Image.LANCZOS)
            return ImageTk.PhotoImage(img)
        photo = tk.PhotoImage(file=str(path))
        scale = max(1, REVIEW_IMAGE_MAX_DIM // max(photo.width(), photo.height()))
        return photo.zoom(scale, scale) if scale > 1 else photo

    def _commit_current_review_item(self):
        item = self._review_items[self._review_index]
        row = self.last_rows[item.row_index]
        row[item.column] = self.review_value_var.get().strip()
        row[_confidence_column(item.column)] = 100.0
        if row.get("report_type") == "GlaucomaReport" and item.column in DATE_COLUMNS:
            _apply_reviewed_date(row, item.column)
        conf_cols = [c for c in row if c.endswith(CONFIDENCE_SUFFIX) and c != OVERALL_CONFIDENCE_COLUMN]
        if conf_cols:
            row[OVERALL_CONFIDENCE_COLUMN] = round(sum(row[c] for c in conf_cols) / len(conf_cols), 1)
        self._review_row_visited[item.row_index].add(item.column)

    def _review_next(self):
        self._commit_current_review_item()
        if self._review_index == len(self._review_items) - 1:
            self._on_review_close()
            return
        self._review_index += 1
        self._render_review_item()

    def _review_prev(self):
        self._commit_current_review_item()
        if self._review_index > 0:
            self._review_index -= 1
            self._render_review_item()

    def _on_review_close(self):
        if self._review_items:
            self._commit_current_review_item()
        resolved = 0
        for row_index, total in self._review_row_totals.items():
            if len(self._review_row_visited.get(row_index, ())) >= total:
                self.last_rows[row_index]["needs_human_review"] = False
                self.last_rows[row_index]["human_reviewed"] = True
                resolved += 1
        self._write_rows_to_csv(self.last_rows)

        still_flagged = sum(1 for r in self.last_rows if r.get("needs_human_review"))
        self._log(f"\nHuman review: {resolved} report(s) marked reviewed. {still_flagged} still flagged.")
        self.status_var.set(f"Human review saved. {still_flagged} report(s) still flagged.")

        if self._review_win is not None:
            self._review_win.destroy()
        self._review_win = None
        self._review_items = []
        self.run_button.state(["!disabled"])
        self.review_button.state(["!disabled"] if still_flagged else ["disabled"])


def main():
    root = tk.Tk()
    ExtractionGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()

"""Batch-extract data from every OCT report image in reference/ into a CSV."""
import sys
import time
from pathlib import Path

from config import settings
from src.extract import extract_report
from src.output import write_rows_csv


def main():
    input_dir = Path(settings.INPUT_DIR)
    image_paths = sorted(
        p for p in input_dir.iterdir() if p.suffix.lower() in settings.INPUT_EXTENSIONS
    )
    if not image_paths:
        print(f"No images found in {input_dir}/")
        sys.exit(1)

    print(f"Found {len(image_paths)} image(s) in {input_dir}/")
    rows = []
    flagged = 0
    start = time.time()

    for i, path in enumerate(image_paths, 1):
        row = extract_report(path)
        rows.append(row)
        if row.get("needs_human_review"):
            flagged += 1
        if i % 50 == 0 or i == len(image_paths):
            print(f"  processed {i}/{len(image_paths)}")

    out_path = Path(settings.OUTPUT_CSV)
    write_rows_csv(rows, out_path)

    elapsed = time.time() - start
    print(f"\nWrote {len(rows)} rows to {out_path} in {elapsed:.1f}s")
    print(f"Flagged for human review: {flagged}/{len(rows)}")
    if flagged:
        print(f"Review crops saved under {settings.REVIEW_DIR}/<filename>/")


if __name__ == "__main__":
    main()

"""CSV writing shared by main.py and the GUI."""
import csv
from pathlib import Path

import pandas as pd


def write_rows_csv(rows: list[dict], path: Path):
    """Write extracted rows to `path`, quoting every field.

    Several values contain "/" -- DD/MM/YYYY dates, and the "R/L eye" /
    "C/D Area Ratio" headers. A spreadsheet import set to also split on "/"
    (LibreOffice remembers "Other" separators between imports) otherwise
    splits those into extra cells and shifts every later column out from
    under its header. A separator inside a quoted field is never treated as
    one, so quoting keeps each value in its own column whatever the viewer's
    separator settings are.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, quoting=csv.QUOTE_ALL)

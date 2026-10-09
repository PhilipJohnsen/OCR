#!/usr/bin/env bash
# Builds the Linux or macOS OCTReportExtractor binary via PyInstaller. Run on
# the actual target OS -- see scripts/vendor_tesseract_unix.sh for why this
# can't cross-compile from Windows.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" == "Darwin" ]]; then
    PLATFORM_DIR="macos"
else
    PLATFORM_DIR="linux"
fi

if [[ ! -f "$REPO_ROOT/vendor/tesseract/$PLATFORM_DIR/tesseract" ]]; then
    echo "No vendored Tesseract found -- running vendor_tesseract_unix.sh first..."
    "$REPO_ROOT/scripts/vendor_tesseract_unix.sh"
fi

cd "$REPO_ROOT"
pyinstaller oct_extractor.spec --noconfirm

echo
echo "Built: $REPO_ROOT/dist/OCTReportExtractor/OCTReportExtractor"

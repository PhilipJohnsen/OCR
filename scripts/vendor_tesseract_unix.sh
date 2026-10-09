#!/usr/bin/env bash
# Copies a local Tesseract-OCR install (+ its shared library dependencies)
# into vendor/tesseract/linux/ or vendor/tesseract/macos/ so PyInstaller can
# bundle it -- end users of the built app won't need Tesseract installed
# separately.
#
# Run this on the actual target OS (a Linux box for the Linux build, a Mac
# for the macOS build -- this repo can't cross-compile a Linux binary from
# Windows or vice versa) with Tesseract already installed system-wide:
#   Linux:  sudo apt-get install tesseract-ocr   (or your distro's equivalent)
#   macOS:  brew install tesseract
#
# CAVEAT (Linux only): a binary built by vendoring glibc's shared libs is only
# as portable as the glibc it was linked against -- it'll run on machines with
# an equal-or-newer glibc, not older ones. For a build meant to run on distros
# older than your build machine, build inside a matching (or manylinux-style)
# container instead of running this directly. This script does NOT copy
# libc/libpthread/libdl/libm/librt/ld-linux -- those come from the target
# machine, which is the standard approach, but is exactly what makes glibc
# version compatibility the thing to watch.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$(uname -s)" == "Darwin" ]]; then
    PLATFORM_DIR="macos"
else
    PLATFORM_DIR="linux"
fi
TARGET_DIR="$REPO_ROOT/vendor/tesseract/$PLATFORM_DIR"
TARGET_TESSDATA="$TARGET_DIR/tessdata"

TESSERACT_BIN="$(command -v tesseract || true)"
if [[ -z "$TESSERACT_BIN" ]]; then
    echo "ERROR: tesseract not found on PATH. Install it first:" >&2
    echo "  Linux:  sudo apt-get install tesseract-ocr" >&2
    echo "  macOS:  brew install tesseract" >&2
    exit 1
fi
echo "Vendoring Tesseract from: $TESSERACT_BIN"
echo "Into:                     $TARGET_DIR"

mkdir -p "$TARGET_DIR" "$TARGET_TESSDATA"
cp "$TESSERACT_BIN" "$TARGET_DIR/tesseract"
chmod +x "$TARGET_DIR/tesseract"

if [[ "$PLATFORM_DIR" == "macos" ]]; then
    # otool -L only lists *direct* deps, so walk the graph until it stops growing.
    collect_deps() {
        local bin="$1"
        otool -L "$bin" 2>/dev/null | tail -n +2 | awk '{print $1}' \
            | grep -vE '^(/usr/lib/|/System/)' || true
    }
    declare -A seen
    to_visit=("$TESSERACT_BIN")
    while [[ ${#to_visit[@]} -gt 0 ]]; do
        current="${to_visit[0]}"
        to_visit=("${to_visit[@]:1}")
        [[ -n "${seen[$current]:-}" ]] && continue
        seen[$current]=1
        for dep in $(collect_deps "$current"); do
            [[ -n "${seen[$dep]:-}" ]] && continue
            to_visit+=("$dep")
        done
    done
    for lib in "${!seen[@]}"; do
        [[ "$lib" == "$TESSERACT_BIN" ]] && continue
        cp -n "$lib" "$TARGET_DIR/" 2>/dev/null || true
    done
else
    # ldd resolves the full transitive closure already; drop the base glibc
    # pieces that must come from the target machine instead of being bundled.
    ldd "$TESSERACT_BIN" | awk '{print $3}' | grep -v '^$' \
        | grep -vE '/(libc|libm|libpthread|libdl|librt|ld-linux)[^/]*\.so' \
        | while read -r lib; do
            cp -n "$lib" "$TARGET_DIR/" 2>/dev/null || true
        done
fi

TESSDATA_SRC="$(dirname "$(dirname "$TESSERACT_BIN")")/share/tessdata/eng.traineddata"
if [[ ! -f "$TESSDATA_SRC" ]]; then
    # Common alternate layout (Debian/Ubuntu packages tessdata under this path).
    TESSDATA_SRC="/usr/share/tesseract-ocr/*/tessdata/eng.traineddata"
    TESSDATA_SRC="$(ls $TESSDATA_SRC 2>/dev/null | head -1 || true)"
fi
if [[ -z "$TESSDATA_SRC" || ! -f "$TESSDATA_SRC" ]]; then
    echo "ERROR: couldn't locate eng.traineddata automatically -- find it and copy it to" >&2
    echo "  $TARGET_TESSDATA/eng.traineddata" >&2
    exit 1
fi
cp "$TESSDATA_SRC" "$TARGET_TESSDATA/eng.traineddata"

file_count=$(find "$TARGET_DIR" -type f | wc -l)
total_size=$(du -sh "$TARGET_DIR" | cut -f1)
echo "Done: $file_count files, $total_size in $TARGET_DIR"

<#
.SYNOPSIS
  Copies a local Tesseract-OCR install into vendor/tesseract/windows/ so
  PyInstaller can bundle it into the packaged app -- end users of the built
  .exe won't need Tesseract installed separately.

.DESCRIPTION
  Run this on a Windows machine that already has Tesseract-OCR installed
  (https://github.com/UB-Mannheim/tesseract/wiki), before running
  scripts\build_windows.ps1. Only tesseract.exe, its runtime DLLs, and the
  English language data are copied -- not the training tools, docs, or other
  language packs -- to keep the bundle reasonably sized (~160MB, dominated by
  libtesseract-5.dll and libicudt75.dll, which can't be trimmed further).

  Re-run this any time you update your system's Tesseract install and want
  the bundled copy to match.
#>
param(
    [string]$SourceDir = "$env:ProgramFiles\Tesseract-OCR"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$TargetDir = Join-Path $RepoRoot "vendor\tesseract\windows"
$TargetTessdata = Join-Path $TargetDir "tessdata"

if (-not (Test-Path (Join-Path $SourceDir "tesseract.exe"))) {
    $cmd = Get-Command tesseract.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        $SourceDir = Split-Path -Parent $cmd.Source
    } else {
        Write-Error "Couldn't find tesseract.exe in '$SourceDir' or on PATH. Install Tesseract-OCR first (https://github.com/UB-Mannheim/tesseract/wiki), or pass -SourceDir explicitly."
        exit 1
    }
}

Write-Host "Vendoring Tesseract from: $SourceDir"
Write-Host "Into:                     $TargetDir"

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
New-Item -ItemType Directory -Force -Path $TargetTessdata | Out-Null

Copy-Item -Path (Join-Path $SourceDir "tesseract.exe") -Destination $TargetDir -Force
Copy-Item -Path (Join-Path $SourceDir "*.dll") -Destination $TargetDir -Force

$EngTrainedData = Join-Path $SourceDir "tessdata\eng.traineddata"
if (-not (Test-Path $EngTrainedData)) {
    Write-Error "eng.traineddata not found under $SourceDir\tessdata -- is this a complete Tesseract install?"
    exit 1
}
Copy-Item -Path $EngTrainedData -Destination $TargetTessdata -Force

$fileCount = (Get-ChildItem -Path $TargetDir -Recurse -File).Count
$totalSize = [math]::Round(((Get-ChildItem -Path $TargetDir -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB), 1)
Write-Host "Done: $fileCount files, $totalSize MB in $TargetDir"

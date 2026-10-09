<#
.SYNOPSIS
  Builds the Windows OCTReportExtractor.exe via PyInstaller.
#>
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

$VendorBin = Join-Path $RepoRoot "vendor\tesseract\windows\tesseract.exe"
if (-not (Test-Path $VendorBin)) {
    Write-Host "No vendored Tesseract found -- running vendor_tesseract_windows.ps1 first..."
    & (Join-Path $PSScriptRoot "vendor_tesseract_windows.ps1")
}

Push-Location $RepoRoot
try {
    # PyInstaller logs everything (INFO included) to stderr. Under
    # ErrorActionPreference=Stop, Windows PowerShell 5.1 turns the first
    # stderr line of a native command into a terminating error and aborts the
    # build -- so relax it for this one call and judge success by exit code.
    $ErrorActionPreference = "Continue"
    pyinstaller oct_extractor.spec --noconfirm 2>&1 | ForEach-Object { "$_" }
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($exitCode -ne 0) {
        throw "pyinstaller exited with code $exitCode"
    }
} finally {
    Pop-Location
}

$DistDir = Join-Path $RepoRoot "dist\OCTReportExtractor"
$ZipPath = Join-Path $RepoRoot "dist\OCTReportExtractor-win64.zip"
Write-Host "`nZipping $DistDir -> $ZipPath ..."
if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $DistDir -DestinationPath $ZipPath

Write-Host "`nBuilt: $DistDir\OCTReportExtractor.exe"
Write-Host "Zipped: $ZipPath"

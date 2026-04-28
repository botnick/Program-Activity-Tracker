<#
.SYNOPSIS
  Package Activity Tracker as a slim, ready-to-run release zip.

.DESCRIPTION
  Output: release/ActivityTracker-v{version}/  + matching .zip.

  The release contains only what an end user needs to double-click
  start.bat and use the tool:
    - backend/ Python source
    - service/__init__.py + capture_service.py
    - service/native/build/tracker_capture.exe (pre-built)
    - ui/dist/ (pre-built UI)
    - start.bat / stop.bat / requirements.txt / README.txt

  No C++ source, no UI source, no tests, no dev deps.

.PARAMETER Version
  Override the version string. Default: read from pyproject.toml.

.PARAMETER SkipBuild
  Do NOT auto-build the native binary or the UI; fail if missing.
  Useful in CI where build steps run before this script.

.PARAMETER OutputDir
  Where to place the release folder + zip. Default: <repo>/release.

.EXAMPLE
  pwsh -File scripts/build-release.ps1
  pwsh -File scripts/build-release.ps1 -Version 0.3.0 -SkipBuild
#>

[CmdletBinding()]
param(
    [string]$Version,
    [switch]$SkipBuild,
    [string]$OutputDir,

    # CI passes these so the script does not have to bootstrap them itself.
    # Locally, omit to skip Python bundling and launcher exe — the resulting
    # zip then needs system Python and is meant for dev smoke-testing only.
    [string]$PythonEmbedDir,
    [string]$LauncherExe
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot "release" }

# --- resolve version ------------------------------------------------------
if (-not $Version) {
    $line = Get-Content (Join-Path $repoRoot "pyproject.toml") |
        Where-Object { $_ -match '^\s*version\s*=\s*"' } |
        Select-Object -First 1
    if (-not $line) { throw "Could not read version from pyproject.toml" }
    $Version = ($line -replace '^\s*version\s*=\s*"([^"]+)".*', '$1').Trim()
}

$relName = "ActivityTracker-v$Version"
$relDir  = Join-Path $OutputDir $relName
$relZip  = Join-Path $OutputDir "$relName.zip"

Write-Host ""
Write-Host "==> Building release $relName" -ForegroundColor Cyan
Write-Host "    repo : $repoRoot"
Write-Host "    out  : $relDir"
Write-Host ""

# --- check / build native binary -----------------------------------------
$bin1 = Join-Path $repoRoot "service\native\build\tracker_capture.exe"
$bin2 = Join-Path $repoRoot "service\native\build\Release\tracker_capture.exe"
$nativeExe = $null
if (Test-Path $bin1)        { $nativeExe = $bin1 }
elseif (Test-Path $bin2)    { $nativeExe = $bin2 }

if (-not $nativeExe) {
    if ($SkipBuild) { throw "tracker_capture.exe missing and -SkipBuild was set." }
    Write-Host "==> Building tracker_capture.exe" -ForegroundColor Yellow
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "Visual Studio not found. Install VS 2022+ with the C++ workload, or run start.bat once to bootstrap."
    }
    $vsPath = & $vswhere -latest -property installationPath
    if (-not $vsPath) { throw "vswhere did not return an installation path." }
    $vsDevCmd = Join-Path $vsPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path $vsDevCmd)) { throw "VsDevCmd.bat not found at $vsDevCmd" }

    $cmakeCmd  = "cmake -S service\native -B service\native\build -G Ninja -DCMAKE_BUILD_TYPE=Release"
    $buildCmd  = "cmake --build service\native\build --config Release"
    & cmd /c """$vsDevCmd"" -arch=amd64 && $cmakeCmd && $buildCmd"
    if ($LASTEXITCODE -ne 0) { throw "Native build failed (exit $LASTEXITCODE)" }

    if (Test-Path $bin1)     { $nativeExe = $bin1 }
    elseif (Test-Path $bin2) { $nativeExe = $bin2 }
    if (-not $nativeExe)     { throw "tracker_capture.exe still missing after build." }
}
Write-Host "    [ok] native: $nativeExe" -ForegroundColor Green

# --- check / build UI -----------------------------------------------------
$uiIndex = Join-Path $repoRoot "ui\dist\index.html"
if (-not (Test-Path $uiIndex)) {
    if ($SkipBuild) { throw "ui\dist\index.html missing and -SkipBuild was set." }
    Write-Host "==> Building ui/dist" -ForegroundColor Yellow
    Push-Location (Join-Path $repoRoot "ui")
    try {
        if (-not (Test-Path "node_modules")) {
            & npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed (exit $LASTEXITCODE)" }
        }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed (exit $LASTEXITCODE)" }
    } finally {
        Pop-Location
    }
}
Write-Host "    [ok] ui:     $uiIndex" -ForegroundColor Green

# --- prepare release dir --------------------------------------------------
if (Test-Path $relDir) {
    Write-Host "==> Cleaning old $relName" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $relDir
}
New-Item -ItemType Directory -Force -Path $relDir | Out-Null

# --- copy backend (skip __pycache__) -------------------------------------
Write-Host "==> Copying backend/" -ForegroundColor Cyan
$backendDest = Join-Path $relDir "backend\app"
New-Item -ItemType Directory -Force -Path $backendDest | Out-Null
Copy-Item (Join-Path $repoRoot "backend\app\*") -Destination $backendDest -Recurse -Exclude "__pycache__"
Get-ChildItem -Path $backendDest -Recurse -Force -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# --- copy service (only what's needed) -----------------------------------
Write-Host "==> Copying service/" -ForegroundColor Cyan
$serviceDest = Join-Path $relDir "service"
New-Item -ItemType Directory -Force -Path $serviceDest | Out-Null
Copy-Item (Join-Path $repoRoot "service\__init__.py")        $serviceDest
Copy-Item (Join-Path $repoRoot "service\capture_service.py") $serviceDest

$nativeDest = Join-Path $serviceDest "native\build"
New-Item -ItemType Directory -Force -Path $nativeDest | Out-Null
Copy-Item $nativeExe (Join-Path $nativeDest "tracker_capture.exe")

# --- copy ui/dist --------------------------------------------------------
Write-Host "==> Copying ui/dist" -ForegroundColor Cyan
$uiDest = Join-Path $relDir "ui\dist"
New-Item -ItemType Directory -Force -Path $uiDest | Out-Null
Copy-Item (Join-Path $repoRoot "ui\dist\*") -Destination $uiDest -Recurse

# --- copy mcp/ source + .mcp.json ----------------------------------------
Write-Host "==> Copying mcp/ + .mcp.json" -ForegroundColor Cyan
$mcpDest = Join-Path $relDir "mcp"
New-Item -ItemType Directory -Force -Path $mcpDest | Out-Null
Copy-Item (Join-Path $repoRoot "mcp\pyproject.toml") $mcpDest
if (Test-Path (Join-Path $repoRoot "mcp\README.md")) {
    Copy-Item (Join-Path $repoRoot "mcp\README.md") $mcpDest
}
$mcpSrcDest = Join-Path $mcpDest "src"
New-Item -ItemType Directory -Force -Path $mcpSrcDest | Out-Null
Copy-Item (Join-Path $repoRoot "mcp\src\*") -Destination $mcpSrcDest -Recurse -Exclude "__pycache__"
Get-ChildItem -Path $mcpSrcDest -Recurse -Force -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Copy-Item (Join-Path $repoRoot ".mcp.json") $relDir

# --- copy release templates ----------------------------------------------
# Only README.txt + requirements.txt go into the zip. start.bat / stop.bat
# stay in the repo for dev convenience but are NOT part of the release —
# tracker.exe replaces both.
Write-Host "==> Copying release templates" -ForegroundColor Cyan
$tplDir = Join-Path $repoRoot "scripts\release-template"
foreach ($f in @("README.txt", "requirements.txt")) {
    $src = Join-Path $tplDir $f
    if (-not (Test-Path $src)) { throw "Missing template: $src" }
    Copy-Item $src $relDir
}

# --- bundled Python (embeddable) -----------------------------------------
if ($PythonEmbedDir) {
    if (-not (Test-Path $PythonEmbedDir)) {
        throw "PythonEmbedDir does not exist: $PythonEmbedDir"
    }
    Write-Host "==> Copying bundled Python" -ForegroundColor Cyan
    $pyDest = Join-Path $relDir "python"
    New-Item -ItemType Directory -Force -Path $pyDest | Out-Null
    Copy-Item (Join-Path $PythonEmbedDir "*") -Destination $pyDest -Recurse
} else {
    Write-Host "    [skip] no PythonEmbedDir; release will need system Python" -ForegroundColor Yellow
}

# --- launcher tracker.exe -------------------------------------------------
if ($LauncherExe) {
    if (-not (Test-Path $LauncherExe)) {
        throw "LauncherExe does not exist: $LauncherExe"
    }
    Write-Host "==> Copying tracker.exe (launcher)" -ForegroundColor Cyan
    Copy-Item $LauncherExe (Join-Path $relDir "tracker.exe")
} else {
    Write-Host "    [skip] no LauncherExe; release will be missing tracker.exe" -ForegroundColor Yellow
}

# --- defender exclusion helper (optional, useful) ------------------------
$scriptsDest = Join-Path $relDir "scripts"
New-Item -ItemType Directory -Force -Path $scriptsDest | Out-Null
Copy-Item (Join-Path $repoRoot "scripts\setup-defender-exclusion.ps1") $scriptsDest

# --- write VERSION marker -------------------------------------------------
Set-Content -Path (Join-Path $relDir "VERSION") -Value $Version -Encoding ASCII

# --- zip ------------------------------------------------------------------
Write-Host "==> Creating $relName.zip" -ForegroundColor Cyan
if (Test-Path $relZip) { Remove-Item $relZip -Force }
Compress-Archive -Path $relDir -DestinationPath $relZip -CompressionLevel Optimal

# --- summary --------------------------------------------------------------
$sizeMB = (Get-Item $relZip).Length / 1MB
Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host " Release ready" -ForegroundColor Green
Write-Host "   version : $Version"
Write-Host "   folder  : $relDir"
Write-Host "   zip     : $relZip"
Write-Host ("   size    : {0:N1} MB" -f $sizeMB)
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""

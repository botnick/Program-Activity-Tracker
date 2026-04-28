<#
.SYNOPSIS
  Bump pyproject.toml version, commit, tag, and push so a new release builds.

.DESCRIPTION
  One-shot helper to ship a release. Picks the next version automatically:
    -Patch (default) bumps 0.2.1 -> 0.2.2
    -Minor            bumps 0.2.1 -> 0.3.0
    -Major            bumps 0.2.1 -> 1.0.0
    -Version 1.2.3    overrides the auto-bump

  Then:
    1. writes the new version into pyproject.toml
    2. commits as "release vX.Y.Z"
    3. tags vX.Y.Z
    4. pushes master + the tag

  The push triggers .github/workflows/release.yml, which builds tracker.exe,
  the bundled Python, and the zip, then attaches it to a GitHub Release.

.EXAMPLE
  pwsh -File scripts/bump-and-release.ps1            # patch bump
  pwsh -File scripts/bump-and-release.ps1 -Minor
  pwsh -File scripts/bump-and-release.ps1 -Version 0.5.0
#>

[CmdletBinding(DefaultParameterSetName = "Auto")]
param(
    [Parameter(ParameterSetName = "Auto")][switch]$Patch,
    [Parameter(ParameterSetName = "Auto")][switch]$Minor,
    [Parameter(ParameterSetName = "Auto")][switch]$Major,
    [Parameter(ParameterSetName = "Override")][string]$Version
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot

# --- read current version from pyproject.toml ----------------------------
$pyproj = Join-Path $repoRoot "pyproject.toml"
$line = Get-Content $pyproj | Where-Object { $_ -match '^\s*version\s*=\s*"' } | Select-Object -First 1
if (-not $line) { throw "Could not read version from pyproject.toml" }
$current = ($line -replace '^\s*version\s*=\s*"([^"]+)".*', '$1').Trim()
if ($current -notmatch '^(\d+)\.(\d+)\.(\d+)$') {
    throw "Current version '$current' is not in semver format"
}
$cMajor = [int]$Matches[1]
$cMinor = [int]$Matches[2]
$cPatch = [int]$Matches[3]

# --- decide new version --------------------------------------------------
if ($Version) {
    if ($Version -notmatch '^(\d+)\.(\d+)\.(\d+)$') { throw "-Version must be MAJOR.MINOR.PATCH" }
    $next = $Version
} elseif ($Major) {
    $next = "$($cMajor + 1).0.0"
} elseif ($Minor) {
    $next = "$($cMajor).$($cMinor + 1).0"
} else {
    $next = "$($cMajor).$($cMinor).$($cPatch + 1)"
}
Write-Host "==> $current  ->  $next" -ForegroundColor Cyan

# --- guardrails ----------------------------------------------------------
$status = git status --porcelain
if ($status) {
    Write-Host "Uncommitted changes:" -ForegroundColor Yellow
    Write-Host $status
    $ans = Read-Host "Continue and amend them into the release commit? (y/N)"
    if ($ans -notmatch '^y') {
        throw "Aborted - commit or stash your changes first."
    }
}

if (git tag --list "v$next") {
    throw "Tag v$next already exists. Pick a different version."
}

# --- bump version --------------------------------------------------------
(Get-Content $pyproj) `
    -replace ('^(\s*version\s*=\s*)"' + [regex]::Escape($current) + '"'), "`$1`"$next`"" |
    Set-Content $pyproj -Encoding UTF8

# --- commit + tag + push -------------------------------------------------
git add pyproject.toml
git commit -m "release v$next"
git tag "v$next"
git push origin HEAD
git push origin "v$next"

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host " v$next pushed - release.yml is now building the zip." -ForegroundColor Green
Write-Host " Watch: https://github.com/botnick/Program-Activity-Tracker/actions" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green

<#
  update-wow.ps1 -- fetch the latest server patches for your WoW 3.3.5a client. Windows.

  Easiest: double-click update-wow.bat, which just runs this.
  Or:      right-click this file -> "Run with PowerShell"
  Or:      powershell -ExecutionPolicy Bypass -File update-wow.ps1 "C:\Games\WoW 3.3.5a"

  It only downloads a file when your copy differs from the server's. Nothing else in your client
  is touched -- not your addons, not your settings, not your realmlist.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)] [string] $WowPath,
    [string] $ManifestUrl = $(if ($env:WOW_MANIFEST_URL) { $env:WOW_MANIFEST_URL }
                             else { 'https://wow.allahaema.net/files/patches.json' })
)

$ErrorActionPreference = 'Stop'
# TLS 1.2 is not the default on stock Windows PowerShell 5.1, and without it Invoke-WebRequest
# fails against a modern server with an unhelpful "could not create SSL/TLS secure channel".
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Ok   ($m) { Write-Host "  ok      $m" -ForegroundColor Green }
function Upd  ($m) { Write-Host "  updated $m" -ForegroundColor Yellow }
function Fail ($m) { Write-Host "  error   $m" -ForegroundColor Red }

# --- find the WoW folder ---------------------------------------------------------------------
if (-not $WowPath) {
    if     (Test-Path (Join-Path $PWD              'Wow.exe')) { $WowPath = $PWD }
    elseif (Test-Path (Join-Path $PSScriptRoot     'Wow.exe')) { $WowPath = $PSScriptRoot }
}
if (-not $WowPath -or -not (Test-Path (Join-Path $WowPath 'Wow.exe'))) {
    Fail 'could not find your WoW folder.'
    Write-Host '        Put this script next to Wow.exe and run it there, or pass the path:'
    Write-Host '          .\update-wow.ps1 "C:\Games\WoW 3.3.5a"'
    if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Press Enter to close' }
    exit 1
}
$WowPath = (Resolve-Path $WowPath).Path

Write-Host ''
Write-Host "WoW folder: $WowPath"
Write-Host "manifest:   $ManifestUrl" -ForegroundColor DarkGray
Write-Host ''

try {
    # -UseBasicParsing matters on older boxes: without it this can block on Internet Explorer's
    # first-run configuration, which is a very confusing hang on a machine with no IE set up.
    $manifest = Invoke-RestMethod -Uri $ManifestUrl -UseBasicParsing -TimeoutSec 30
} catch {
    Fail "could not reach the update server. Is it up?  ($($_.Exception.Message))"
    if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Press Enter to close' }
    exit 1
}

$base = $manifest.base_url
if (-not $base) { $base = ($ManifestUrl -replace '/[^/]+$', '') + '/patches/' }

$changed = 0
foreach ($p in $manifest.patches) {
    $target = Join-Path $WowPath ($p.dest -replace '/', '\')

    if (Test-Path $target) {
        $have = (Get-FileHash -Path $target -Algorithm SHA256).Hash.ToLower()
        if ($have -eq $p.sha256.ToLower()) { Ok $p.dest; continue }
    }

    $dir = Split-Path $target -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    Write-Host "  ...     downloading $($p.dest)" -ForegroundColor DarkGray
    $tmp = "$target.part"
    try {
        # ProgressPreference off: the progress bar makes Invoke-WebRequest dramatically slower
        # on large files in Windows PowerShell 5.1 -- a well-known and very real difference.
        $oldProgress = $ProgressPreference; $ProgressPreference = 'SilentlyContinue'
        Invoke-WebRequest -Uri ($base + $p.file) -OutFile $tmp -UseBasicParsing -TimeoutSec 600
        $ProgressPreference = $oldProgress
    } catch {
        Fail "download failed: $($p.file)  ($($_.Exception.Message))"
        if (Test-Path $tmp) { Remove-Item $tmp -Force }
        if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Press Enter to close' }
        exit 1
    }

    $got = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $p.sha256.ToLower()) {
        Fail "checksum mismatch on $($p.file) -- the download is corrupt, not applying it."
        Write-Host "          expected $($p.sha256.ToLower())"
        Write-Host "          got      $got"
        Remove-Item $tmp -Force
        if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Press Enter to close' }
        exit 1
    }

    # Replace only after the checksum passes: an interrupted run must never leave a half-written
    # MPQ behind, because the client will happily try to load it and behave strangely.
    Move-Item -Path $tmp -Destination $target -Force
    Upd $p.dest
    $changed++
}

Write-Host ''
if ($changed -eq 0) {
    Write-Host 'Already up to date. Nothing downloaded.' -ForegroundColor Green
} else {
    Write-Host "Updated $changed file(s). Restart WoW if it is running." -ForegroundColor Yellow
}
Write-Host ''
if ($Host.Name -eq 'ConsoleHost') { Read-Host 'Press Enter to close' }

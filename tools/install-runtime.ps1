# Put the Electron runtime in %LOCALAPPDATA%\ClaudePet\electron.
#
# Why not next to the pet: sandboxed coding agents (e.g. OpenAI Codex on Windows) may stamp
# their workspace folder with a LOW integrity label. Any exe launched from inside it then
# runs at low integrity, Chromium cannot create its sandbox, and Electron dies at once
# (exit 0x80000003, "crashpad not connected"). A runtime under %LOCALAPPDATA% is unaffected.
#
# Source, first match: -From <dir>, or .\electron\ beside the pet (shipped in the release zip).
param([string]$From)
$ErrorActionPreference = 'Stop'
$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$dst = Join-Path $env:LOCALAPPDATA 'ClaudePet\electron'

$cands = @()
if ($From) { $cands += $From }
$cands += (Join-Path $root 'electron')
$src = $cands | Where-Object { Test-Path (Join-Path $_ 'electron.exe') } | Select-Object -First 1
if (-not $src) { 'No Electron runtime found. Pass -From <folder containing electron.exe>.'; exit 1 }

New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item (Join-Path $src '*') $dst -Recurse -Force
'Copied Electron runtime'
'  from ' + $src
'  to   ' + $dst
$label = (icacls (Join-Path $dst 'electron.exe')) -match 'Low Mandatory'
if ($label) { 'WARNING: the copy still carries a Low integrity label.' } else { 'Integrity: normal (Medium).' }

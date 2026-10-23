@echo off
rem ============================================================
rem  Claude-chan desktop pet launcher (Electron)
rem
rem  Keep this file pure ASCII: cmd.exe mis-parses UTF-8 batch files
rem  (multi-byte characters break the line reader even after chcp 65001).
rem
rem  Electron runtime, first match:
rem    1. %LOCALAPPDATA%\ClaudePet\electron   (set up by tools\install-runtime.ps1)
rem    2. electron\ next to this file (shipped in the release zip)
rem  1 is preferred: if this folder sits inside a sandboxed coding agent's workspace
rem  (e.g. OpenAI Codex on Windows) it may carry a LOW integrity label; an exe started
rem  from there runs at low integrity, Chromium cannot build its sandbox and Electron
rem  dies at once (0x80000003). %LOCALAPPDATA% is not affected.
rem  Never add -WindowStyle Hidden: Kaspersky blocks hidden long-running scripts.
rem ============================================================

rem A shell started from another Electron app (e.g. an editor's terminal) may inherit
rem ELECTRON_RUN_AS_NODE, which turns electron.exe into plain Node and it exits at once.
set "ELECTRON_RUN_AS_NODE="

set "PETDIR=%~dp0"
set "ELECTRON=%LOCALAPPDATA%\ClaudePet\electron\electron.exe"
if exist "%ELECTRON%" goto run
set "ELECTRON=%PETDIR%electron\electron.exe"
if exist "%ELECTRON%" goto run
echo electron.exe not found. Download the release zip (it includes electron\),
echo or put the Electron runtime in %PETDIR%electron\
pause
exit /b 1

:run
rem "start-pet.bat debug" runs in the foreground with Chromium logging, for troubleshooting
if /i "%~1"=="debug" (
  echo Electron: %ELECTRON%
  "%ELECTRON%" --enable-logging "%PETDIR%electron-app"
  echo exit code %ERRORLEVEL%
  exit /b
)
start "" "%ELECTRON%" "%PETDIR%electron-app"

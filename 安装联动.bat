@echo off
rem Hook the pet up to Claude Code (merges hooks into %USERPROFILE%\.claude\settings.json, backup first).
rem Keep this file pure ASCII. Needs Node.js. Pass "uninstall" to remove the hooks again.
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js not found. Install it from https://nodejs.org/ and run this again.
  pause
  exit /b 1
)
if /i "%~1"=="uninstall" (
  node "%~dp0hooks\install-hooks.js" --uninstall
) else (
  node "%~dp0hooks\install-hooks.js"
)
pause

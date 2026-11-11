@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Run setup_radar.bat first.
  pause
  exit /b 1
)
if not exist "radar.json" (
  echo [ERROR] Run setup_radar.bat or copy radar.example.json to radar.json.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" radar.py
set "APP_EXIT=%ERRORLEVEL%"
pause
exit /b %APP_EXIT%

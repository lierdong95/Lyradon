@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Run setup_stargaze.bat first.
  pause
  exit /b 1
)
if not exist "stargaze.json" (
  echo [ERROR] Run setup_stargaze.bat or copy stargaze.example.json to stargaze.json.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" stargaze.py
set "APP_EXIT=%ERRORLEVEL%"
pause
exit /b %APP_EXIT%

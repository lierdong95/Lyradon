@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Run setup_scheduler.bat first.
  pause
  exit /b 1
)
if not exist "schedule.json" (
  echo [ERROR] Run setup_scheduler.bat or copy schedule.example.json to schedule.json.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scheduler.py
set "APP_EXIT=%ERRORLEVEL%"
pause
exit /b %APP_EXIT%

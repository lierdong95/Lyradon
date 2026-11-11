@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Run setup_wordlib.bat first.
  pause
  exit /b 1
)
if not exist "wordlib.json" (
  echo [ERROR] Run setup_wordlib.bat or copy wordlib.example.json to wordlib.json.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" wordlib.py
set "APP_EXIT=%ERRORLEVEL%"
pause
exit /b %APP_EXIT%

@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo [ERROR] Python 3.11 or newer must be available as python.
  goto :err
)
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto :err
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :err
if not exist "radar.json" (
  copy /y "radar.example.json" "radar.json" >nul
  if errorlevel 1 goto :err
)
echo Setup complete. Edit radar.json before starting radar.bat.
echo Existing local configuration has been preserved.
pause
exit /b 0
:err
echo [ERROR] Setup failed. Review the error above.
pause
exit /b 1

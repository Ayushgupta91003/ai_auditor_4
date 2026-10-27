@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.11 or newer, then run this setup again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-local.txt
if errorlevel 1 (
  echo Dependency installation failed. Keep this error for troubleshooting.
  pause
  exit /b 1
)
echo Setup complete. Run START_LOCAL.cmd and open http://127.0.0.1:8765
pause

@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import fastapi,langgraph,pymupdf" >nul 2>&1
  if not errorlevel 1 (
    ".venv\Scripts\python.exe" run_local.py
    exit /b
  )
)
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" run_local.py
  exit /b
)
python run_local.py
pause

@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\check_langfuse.py
) else (
  python scripts\check_langfuse.py
)
pause

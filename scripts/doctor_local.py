"""Read-only setup report. Prints presence/status, never secret values."""
import importlib.util
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent.env import load_env
from local_dev.preflight import loopback_status
load_env(ROOT/".env.local")
print("Invoice Auditor laptop readiness")
print("Python:",sys.version.split()[0])
for name in ["fastapi","uvicorn","langgraph","pydantic","httpx","pymupdf","docx","PIL","pytesseract","python_multipart"]:
    print(name+":", "available" if importlib.util.find_spec(name) else "MISSING")
ok,message=loopback_status();print("Localhost:",message)
print("Groq key:","configured (not displayed)" if os.getenv("GROQ_API_KEY") else "not configured; enter in dashboard or .env.local")
print("Groq model:",os.getenv("GROQ_MODEL","qwen/qwen3.8-27b"))
print("AWS and Docker: not needed for the laptop profile")
print("Start: START_LOCAL.cmd, then http://127.0.0.1:8765")

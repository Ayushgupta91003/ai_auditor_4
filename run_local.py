"""One-command laptop launcher; no package installation or administrator prompt."""
import os
from pathlib import Path
from agent.env import load_env
ROOT=Path(__file__).resolve().parent
load_env(ROOT/".env.local")
os.environ.setdefault("LLM_PROVIDER","groq")
os.environ.setdefault("LOCAL_DEVELOPMENT","true")
os.environ.setdefault("EMBEDDING_PROVIDER","local")
if __name__=="__main__":
    from local_dev.preflight import loopback_status
    ok,message=loopback_status()
    if not ok: raise SystemExit(message)
    import uvicorn
    print("Laptop dashboard: http://127.0.0.1:"+os.getenv("LOCAL_PORT","8765"))
    print("No API key needed to open the dashboard. Configure Groq in the UI or .env.local.")
    uvicorn.run("local_dev.main:app",host="127.0.0.1",port=int(os.getenv("LOCAL_PORT","8765")),access_log=False)

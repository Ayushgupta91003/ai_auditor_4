"""Verify a non-sensitive observation using the modern Langfuse SDK/API."""
import os
import time
from pathlib import Path
from datetime import datetime,timezone,timedelta
import sys
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from agent.env import load_env
load_env(ROOT/".env.local");load_env(ROOT/".env")
if not all(os.getenv(k) for k in ("LANGFUSE_PUBLIC_KEY","LANGFUSE_SECRET_KEY")):
    raise SystemExit("Configure both Langfuse keys privately in .env.local first.")
try:from langfuse import get_client
except ImportError:raise SystemExit("Langfuse SDK missing. Run SETUP_LOCAL.cmd first.")
client=get_client()
try:
    if not client.auth_check():raise SystemExit("Langfuse authentication failed; verify keys and regional endpoint.")
    with client.start_as_current_observation(as_type="span",name="invoice-auditor-smoke-check"):
        trace_id=client.get_current_trace_id()
    client.flush()
    print("Langfuse authentication succeeded; non-sensitive test observation submitted.",flush=True)
    base=os.getenv("LANGFUSE_BASE_URL","https://cloud.langfuse.com").rstrip("/")
    if base not in {"https://cloud.langfuse.com","https://us.cloud.langfuse.com","https://jp.cloud.langfuse.com"}:
        raise SystemExit("Automatic read-back is limited to supported cloud regions; inspect your configured self-hosted dashboard manually.")
    for attempt in range(5):
        now=datetime.now(timezone.utc)
        params={"traceId":trace_id,"fromStartTime":(now-timedelta(minutes=15)).isoformat(),"toStartTime":now.isoformat(),"limit":10,"fields":"core,basic"}
        response=httpx.get(base+"/api/public/v2/observations",params=params,
            auth=(os.environ["LANGFUSE_PUBLIC_KEY"],os.environ["LANGFUSE_SECRET_KEY"]),timeout=15)
        if response.status_code==200 and any(x.get("name")=="invoice-auditor-smoke-check" for x in response.json().get("data",[])):
            print("CONFIRMED: test observation is visible in Langfuse. Refresh the project's Tracing page.")
            break
        if attempt<4:time.sleep(5)
    else:raise SystemExit("Observation submitted but read-back not yet confirmed. Check Tracing after ingestion catches up.")
except SystemExit:raise
except Exception:raise SystemExit("Langfuse check failed; verify connectivity and regional endpoint. Credentials were not printed.")

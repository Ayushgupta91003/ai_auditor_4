"""Non-destructive checks for a configured running stack; no credentials printed."""
import json
import os
from pathlib import Path
import socket
import subprocess
import urllib.request
ROOT=Path(__file__).resolve().parents[1]
if (ROOT/".env").exists():
    for line in (ROOT/".env").read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key,value=line.split("=",1); os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
token=os.environ.get("SERVICE_TOKEN","")
if not token: raise SystemExit("Configure SERVICE_TOKEN in .env first")
def get(url,authenticated=False):
    request=urllib.request.Request(url,headers={"Authorization":"Bearer "+token} if authenticated else {})
    with urllib.request.urlopen(request,timeout=15) as response:
        assert response.status==200
        return response.read()
checks=[("Agent", "http://localhost:8000/health",False),
    ("ERP", "http://localhost:8001/health",False),("PO seed","http://localhost:8001/po/PO-1001",False),
    ("Streamlit","http://localhost:8501/_stcore/health",False),("Qdrant","http://localhost:6333/readyz",False),
    ("A2A card","http://localhost:8000/reporting/.well-known/agent-card.json",True),
    ("Audit API","http://localhost:8000/invoices",True)]
for name,url,auth in checks:
    get(url,auth); print(name+": OK")
with socket.create_connection(("localhost",6379),timeout=5) as conn:
    conn.sendall(b"*1\r\n$4\r\nPING\r\n")
    assert conn.recv(100).startswith(b"+PONG")
print("Redis: OK")
result=subprocess.run(["docker","compose","ps","--format","json"],cwd=ROOT,text=True,capture_output=True,check=True)
try: rows=json.loads(result.stdout)
except json.JSONDecodeError: rows=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
if isinstance(rows,dict): rows=[rows]
assert {r["Service"] for r in rows}=={"agent","mock-erp","streamlit-ui","postgres","qdrant","redis"}
assert all(r.get("Health")=="healthy" for r in rows), "Some services are not healthy"
print("Six service health checks: OK")
print("Startup smoke passed. Persistence, end-to-end processing and image-history checks remain separate.")

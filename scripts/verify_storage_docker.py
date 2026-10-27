"""Verify durable stores and deliberate data loss ONLY in a disposable unique Compose project."""
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
PROJECT="invoice-auditor-test-"+uuid4().hex[:10]
assert re.fullmatch(r"invoice-auditor-test-[0-9a-f]{10}",PROJECT)
assert PROJECT!="ai-invoice-auditor"
local=ROOT/".local";local.mkdir(exist_ok=True)
override=local/(PROJECT+".yaml")
override.write_text("""services:
  postgres:
    ports: !reset []
  qdrant:
    ports: !reset []
  redis:
    ports: !reset []
  mock-erp:
    ports: !reset []
  agent:
    ports: !reset []
    environment:
      WATCH_ENABLED: 'false'
  streamlit-ui:
    ports: !reset []
""")
base=["docker","compose","--progress","quiet","-p",PROJECT,"-f",str(ROOT/"compose.yaml"),"-f",str(override)]
log=local/"storage-verification.log"
results=[]
def compose(*args):
    with log.open("a",encoding="utf-8") as stream:
        subprocess.run(base+list(args),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)
def probe(mode):
    payload=(ROOT/"scripts/_storage_probe.py").read_text()
    run=subprocess.run(base+["exec","-T","agent","python","-",mode],input=payload,text=True,cwd=ROOT,capture_output=True)
    if run.returncode:
        with log.open("a",encoding="utf-8") as stream:stream.write(run.stdout+run.stderr)
        raise RuntimeError("Storage probe failed; inspect the private local verification log")
    result=json.loads(run.stdout.strip().splitlines()[-1]);results.append(result)
    print(mode+": PASS",flush=True)
def up():compose("up","-d","--wait","--wait-timeout","180")
print("Disposable verification project:",PROJECT,flush=True)
print("The existing ai-invoice-auditor and thecoach projects will not be stopped or deleted.",flush=True)
try:
    up();probe("seed")
    compose("down");up();probe("retained")
    # This deletes only volumes owned by the unique synthetic test project above.
    compose("down","-v");up();probe("empty")
    (local/"storage-verification.json").write_text(json.dumps({"project":PROJECT,"passed":True,"phases":results,"live_llm_used":False},indent=2))
    print("PASS: raw audit data, line rows, reports, feedback, checkpoints and vectors survived recreation; disposable Redis did not. Isolated -v reset removed durable test data.",flush=True)
finally:
    compose("down","-v")

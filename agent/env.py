"""Load only explicitly selected local env files; never print their values."""
import os
from pathlib import Path

def load_env(path):
    path=Path(path)
    if not path.exists(): return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line=line.strip()
        if not line or line.startswith("#"): continue
        if "=" not in line: raise ValueError("Invalid environment file entry")
        key,value=line.split("=",1)
        key=key.strip()
        if not key.replace("_","").isalnum(): raise ValueError("Invalid environment variable name")
        value=value.strip()
        if len(value)>1 and value[0]==value[-1] and value[0] in (chr(34),chr(39)): value=value[1:-1]
        os.environ.setdefault(key,value)

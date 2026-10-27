"""Create a source-only handoff; never include local secrets, databases or private uploads."""
from pathlib import Path
import zipfile
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/"ai-invoice-auditor-source.zip"
excluded={".venv","__pycache__",".git",".pytest_cache",".local","test-results","dist"}
files=[]
for path in ROOT.rglob("*"):
    if not path.is_file() or path==out: continue
    parts=path.relative_to(ROOT).parts
    if any(p in excluded for p in parts): continue
    if path.name.startswith(".env") and path.name not in (".env.example",".env.local.example"): continue
    if parts[:2] in (("data","incoming"),("data","reports")) and path.name!=".gitkeep": continue
    files.append(path)
with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as archive:
    for path in files: archive.write(path,"ai-invoice-auditor/"+path.relative_to(ROOT).as_posix())
print("Source package:",out)
print("Files:",len(files))

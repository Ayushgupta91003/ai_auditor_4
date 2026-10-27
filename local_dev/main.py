"""Loopback-only laptop API + dashboard. No Docker, AWS, or elevated permissions."""
import os
from pathlib import Path
from agent.env import load_env
ROOT=Path(__file__).resolve().parents[1]
load_env(ROOT/".env.local")
os.environ.setdefault("LLM_PROVIDER","groq")
os.environ.setdefault("LOCAL_DEVELOPMENT","true")
os.environ.setdefault("EMBEDDING_PROVIDER","local")
import asyncio
import json
import secrets
from contextlib import asynccontextmanager,suppress
from uuid import UUID,uuid4
from fastapi import FastAPI,UploadFile,File,HTTPException,Request
from fastapi.responses import HTMLResponse,JSONResponse,Response
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel,Field
from agent.settings import settings
from agent.models import Correction,Question
from agent.groq_client import ProviderError,models as groq_models
from agent.report_format import render_html
from local_dev.store import Store
from local_dev.engine import Engine
from local_dev.erp import router as erp_router
TOKEN=secrets.token_urlsafe(32)
INCOMING=ROOT/".local/incoming"
store=Store()
engine=Engine(store,"http://127.0.0.1:"+os.getenv("LOCAL_PORT","8765")+"/erp")

async def watcher():
    seen={}; attempted={}
    while True:
        for path in INCOMING.iterdir():
            if path.suffix.lower() not in (".pdf",".docx",".png"): continue
            stat=path.stat(); fingerprint=(stat.st_size,stat.st_mtime_ns)
            if seen.get(path)!=fingerprint: seen[path]=fingerprint; continue
            if attempted.get(path)==fingerprint: continue
            attempted[path]=fingerprint
            try: await asyncio.to_thread(engine.process,path)
            except Exception: pass # Engine persists the failure for dashboard retry.
        await asyncio.sleep(3)
@asynccontextmanager
async def lifespan(app):
    INCOMING.mkdir(parents=True,exist_ok=True)
    # One-time derived-index migration; original files/reports/feedback remain unchanged.
    if store.get_meta("rag-evidence-version")!="canonical-v1":
        for row in store.list():
            if row["status"]=="completed":await asyncio.to_thread(engine.index,row["id"])
        store.set_meta("rag-evidence-version","canonical-v1")
    task=asyncio.create_task(watcher())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError): await task
app=FastAPI(title="Invoice Auditor - laptop development",lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost"])
app.include_router(erp_router,prefix="/erp")
@app.middleware("http")
async def protect(request:Request,call_next):
    if request.url.path.startswith("/api/"):
        if not secrets.compare_digest(request.headers.get("authorization",""),"Bearer "+TOKEN):
            return JSONResponse({"detail":"Local session token required; refresh the dashboard"},status_code=401)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Cache-Control"]="no-store"
    return response
@app.exception_handler(ProviderError)
async def provider_error(request,error): return JSONResponse({"detail":str(error)},status_code=503)
@app.exception_handler(ValueError)
async def value_error(request,error): return JSONResponse({"detail":str(error)},status_code=400)
@app.exception_handler(KeyError)
async def missing(request,error): return JSONResponse({"detail":"Invoice not found"},status_code=404)
@app.get("/",response_class=HTMLResponse)
def home(): return (ROOT/"local_dev/dashboard.html").read_text(encoding="utf-8").replace("__SESSION_TOKEN__",TOKEN)
@app.get("/health")
def health(): return {"status":"ok","profile":"local-development","provider":settings.provider,"key_configured":bool(os.getenv("GROQ_API_KEY"))}
@app.get("/api/status")
def status():
    import shutil
    return {"provider":settings.provider,"model":settings.model,"key_configured":bool(os.getenv("GROQ_API_KEY")),
        "ocr":"Tesseract" if os.getenv("TESSERACT_CMD") or shutil.which("tesseract") else "Groq vision (requires key and vision model)",
        "database":"SQLite (local development)","vectors":"Local lexical vectors; Groq reranking","incoming":str(INCOMING)}
class ProviderConfig(BaseModel):
    api_key:str=Field(default="",max_length=512)
    model:str=Field(default="qwen/qwen3.8-27b",min_length=1,max_length=150)
@app.post("/api/provider")
def configure(body:ProviderConfig):
    if body.model.startswith(("openai/","gpt-","gemini")): raise ValueError("Choose a non-OpenAI, non-Gemini Groq model")
    if body.api_key.strip(): os.environ["GROQ_API_KEY"]=body.api_key.strip()
    settings.provider="groq"; settings.model=body.model; settings.rag_model=body.model
    os.environ["LLM_PROVIDER"]="groq";os.environ["GROQ_MODEL"]=body.model
    return {"saved_for_session":True,"key_configured":bool(os.getenv("GROQ_API_KEY")),"model":body.model}
@app.get("/api/provider/models")
async def list_models(): return {"models":await asyncio.to_thread(groq_models)}
@app.get("/api/invoices")
def invoices(): return store.list()
@app.get("/api/invoices/{invoice_id}")
def invoice(invoice_id:UUID): return store.get(str(invoice_id))
@app.post("/api/upload")
async def upload(file:UploadFile=File(...)):
    suffix=Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf",".docx",".png"): raise ValueError("Supported: PDF, DOCX, PNG")
    data=await file.read(15*1024*1024+1)
    if len(data)>15*1024*1024: raise HTTPException(413,"Maximum 15 MB")
    if not data: raise ValueError("Invoice is empty")
    path=INCOMING/(str(uuid4())+suffix)
    pending=path.with_suffix(".pending"); pending.write_bytes(data);pending.replace(path)
    return await asyncio.to_thread(engine.process,path)
@app.post("/api/samples/{name}")
async def sample(name:str):
    allowed={"english.pdf","spanish.docx","german.png","german-scanned.pdf"}
    if name not in allowed: raise HTTPException(404,"Sample not found")
    return await asyncio.to_thread(engine.process,ROOT/"samples"/name)
@app.post("/api/invoices/{invoice_id}/retry")
async def retry(invoice_id:UUID):
    await asyncio.to_thread(engine.resume,str(invoice_id))
    return {"invoice_id":str(invoice_id),"status":"completed"}
@app.post("/api/invoices/{invoice_id}/corrections")
async def correction(invoice_id:UUID,body:Correction):
    return await asyncio.to_thread(engine.revalidate,str(invoice_id),body)
@app.post("/api/invoices/{invoice_id}/revalidate")
async def revalidate(invoice_id:UUID): return await asyncio.to_thread(engine.revalidate,str(invoice_id))
@app.get("/api/invoices/{invoice_id}/download/{version}/{format}")
def download(invoice_id:UUID,version:int,format:str):
    row=store.get(str(invoice_id))
    run=next((r for r in row["runs"] if r["version"]==version),None)
    if not run: raise HTTPException(404,"Report version not found")
    export={**run["report"],"invoice":run["input"]}
    if format=="html": return Response(render_html(export),media_type="text/html",headers={"Content-Disposition":"attachment; filename=invoice-report.html"})
    if format=="json": return Response(json.dumps(export,indent=2),media_type="application/json",headers={"Content-Disposition":"attachment; filename=invoice-report.json"})
    raise HTTPException(404,"Choose HTML or JSON")
@app.post("/api/questions")
async def question(body:Question):
    if body.invoice_id: UUID(body.invoice_id)
    return await asyncio.to_thread(engine.question,body.question,body.invoice_id)
@app.post("/api/index/rebuild")
async def rebuild():
    for row in store.list():
        if row["status"]=="completed": await asyncio.to_thread(engine.index,row["id"])
    return {"status":"rebuilt from stored text; no OCR"}

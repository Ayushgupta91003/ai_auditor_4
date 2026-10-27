import asyncio
import logging
import os
import secrets
from contextlib import asynccontextmanager, suppress
from uuid import UUID
import httpx
import redis
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from agent.settings import settings
from agent import repository as repo
from agent.workflow import process,execute,revalidate,watch
from agent.reporting import a2a_app
from agent.rag import init_index, answer_question
from agent.mcp_client import Tools
from agent.models import Correction,Question
logging.basicConfig(level=logging.INFO)
cache=redis.Redis.from_url(settings.redis_url,decode_responses=True)

@asynccontextmanager
async def lifespan(app):
    if not os.getenv("SERVICE_TOKEN"): raise RuntimeError("SERVICE_TOKEN must be configured")
    repo.pool.open(); repo.pool.wait(timeout=20)
    with repo.pool.connection() as c: c.execute("SELECT 1 FROM audit.invoice_audit LIMIT 1")
    cache.ping()
    init_index()
    async with httpx.AsyncClient(timeout=15) as client:
        (await client.get(settings.erp_url+"/health")).raise_for_status()
    # Schema ownership: LangGraph checkpointer creates its tables in langgraph.
    checkpoint_url=settings.database_url + ("&" if "?" in settings.database_url else "?") + "options=-csearch_path%3Dlanggraph"
    async with AsyncPostgresSaver.from_conn_string(checkpoint_url) as saver:
        await saver.setup()
        app.state.saver=saver
        # Mounted Starlette applications do not receive lifespan automatically.
        await a2a_app.router.startup()
        watcher=asyncio.create_task(watch(saver)) if settings.watch else None
        yield
        if watcher:
            watcher.cancel()
            with suppress(asyncio.CancelledError): await watcher
        await a2a_app.router.shutdown()
    repo.pool.close()
app=FastAPI(title="AI Invoice Auditor",lifespan=lifespan)
app.mount("/reporting",a2a_app)
@app.middleware("http")
async def service_auth(request,call_next):
    from fastapi.responses import JSONResponse
    token=os.getenv("SERVICE_TOKEN","")
    if request.url.path != "/health":
        if not token or not secrets.compare_digest(request.headers.get("authorization",""),"Bearer "+token):
            return JSONResponse(status_code=401,content={"detail":"Service token required"})
    return await call_next(request)

@app.get("/health")
def health():
    with repo.pool.connection() as c: c.execute("SELECT 1")
    cache.ping()
    return {"status":"ok"}
@app.get("/invoices")
def invoices(): return repo.list_invoices()
@app.get("/invoices/{invoice_id}")
def invoice(invoice_id:UUID):
    try: return repo.get(str(invoice_id))
    except KeyError: raise HTTPException(404,"Invoice not found")
@app.get("/invoices/{invoice_id}/report",response_class=HTMLResponse)
def report(invoice_id:UUID):
    row=invoice(invoice_id)
    if not row["runs"]: raise HTTPException(404,"No completed report")
    return row["runs"][-1]["html"]
@app.post("/upload")
async def upload(file:UploadFile=File(...)):
    from pathlib import Path
    from uuid import uuid4
    from agent.config import rules
    suffix=Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf",".docx",".png"): raise HTTPException(400,"Supported: PDF, DOCX, PNG")
    data=await file.read(rules()["max_upload_mb"]*1024*1024+1)
    if len(data)>rules()["max_upload_mb"]*1024*1024: raise HTTPException(413,"File too large")
    settings.incoming.mkdir(parents=True,exist_ok=True)
    path=settings.incoming/(str(uuid4())+suffix)
    # Atomic rename avoids watcher reading partially written uploads.
    pending=path.with_suffix(".pending")
    pending.write_bytes(data); pending.replace(path)
    return await process(path,app.state.saver)
@app.post("/invoices/{invoice_id}/retry")
async def retry(invoice_id:UUID):
    row=invoice(invoice_id)
    if row["status"] not in ("failed","processing"): raise HTTPException(409,"Only failed or interrupted invoices can be resumed")
    await execute(str(invoice_id),app.state.saver,resume=True)
    return {"status":"resumed"}
@app.post("/invoices/{invoice_id}/corrections")
async def correct(invoice_id:UUID,correction:Correction):
    try:
        repo.feedback(str(invoice_id),correction)
        return await revalidate(str(invoice_id))
    except (ValueError,StopIteration) as e: raise HTTPException(409,str(e))
@app.post("/invoices/{invoice_id}/revalidate")
async def validate_again(invoice_id:UUID): return await revalidate(str(invoice_id))
@app.post("/questions")
async def question(body:Question):
    if body.invoice_id:
        try: UUID(body.invoice_id)
        except ValueError: raise HTTPException(400,"Invalid invoice ID")
    async with Tools() as tools:
        return await answer_question(body.question,body.invoice_id,tools,cache)
@app.post("/index/rebuild")
async def rebuild():
    from agent.rag import index_invoice
    rows=repo.list_invoices()
    for row in rows:
        if row["status"]=="completed": await asyncio.to_thread(index_invoice,str(row["invoice_id"]))
    return {"status":"rebuilt"}

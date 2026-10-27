import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from agent import repository as repo
from agent.models import Invoice, Finding
from agent.mcp_client import Tools
from agent.validation import recommendation
from agent.reporting import render_html
from agent.report_explanation import checked_explanation
from agent.settings import settings
from agent.observability import trace
log=logging.getLogger(__name__)
class AuditState(TypedDict,total=False):
    invoice_id:str
    path:str
    checksum:str
    raw:str
    translation:dict
    invoice:dict
    findings:list
    advisories:list
    version:int
    report:dict

def build_graph(tools,checkpointer):
    async def monitor(s):
        detected=await tools.call("invoice_watcher",{"path":s["path"]})
        if detected["checksum"]!=s["checksum"]: raise ValueError("File changed after detection; submit the stable file again")
        return {}
    async def extractor(s):
        result=await tools.call("data_harvester",{"path":s["path"]})
        if not result["text"].strip(): raise ValueError("Document has no extractable text")
        repo.raw(s["invoice_id"],result["text"],result["method"])
        return {"raw":result["text"]}
    async def translator(s):
        return {"translation":await tools.call("lang_bridge",{"text":s["raw"]})}
    async def parser(s):
        invoice=await tools.call("invoice_parser",{"text":s["translation"]["text"]})
        invoice=repo.extracted(s["invoice_id"],Invoice.model_validate(invoice),s["translation"])
        return {"invoice":invoice}
    async def completeness(s):
        result=await tools.call("data_completeness_checker",{"invoice":s["invoice"]})
        return {"findings":result["findings"],"advisories":[result["advisory"]]}
    async def business(s):
        result=await tools.call("business_validation",{"invoice":s["invoice"]})
        return {"findings":s["findings"]+result["findings"],"advisories":s["advisories"]+[result["advisory"]]}
    async def reporting(s):
        # PostgreSQL may have committed before the graph checkpoint or file export.
        # Resume that report instead of creating another version or calling ADK again.
        saved=repo.get(s["invoice_id"])["runs"]
        for run in saved:
            if run["version"]==s["version"]+1:
                if run["effective_input"]!=s["invoice"]:
                    raise ValueError("Committed report input differs from checkpoint")
                return {"report":run["report"]}
        confidence=float(s["translation"]["confidence"])
        report={"invoice_id":s["invoice_id"],"version":s["version"]+1,"findings":s["findings"],
            "advisory_notes":s["advisories"],
            "missing_fields":[x["field"] for x in s["findings"] if x["actual"] is None],
            "translation_confidence":confidence,"confidence_note":"Model self-assessment; not a calibrated probability",
            "recommendation":recommendation([Finding.model_validate(f) for f in s["findings"]],confidence)}
        report["invoice"]=s["invoice"]
        text=await tools.call("insight_reporter",{"evidence":report})
        report["explanation"],report["explanation_method"]=checked_explanation(report,text)
        html=render_html(report)
        repo.save_report(s["invoice_id"],Invoice.model_validate(s["invoice"]),report,html,s["version"])
        try:
            settings.reports.mkdir(parents=True,exist_ok=True)
            stem=settings.reports/f"{s['invoice_id']}-v{report['version']}"
            stem.with_suffix(".json").write_text(json.dumps(report,indent=2),encoding="utf-8")
            stem.with_suffix(".html").write_text(html,encoding="utf-8")
        except OSError:
            log.warning("Report saved in PostgreSQL; optional file export unavailable")
        return {"report":report}
    async def indexing(s):
        try: await tools.call("vector_indexer",{"invoice_id":s["invoice_id"]})
        except Exception: log.exception("Audit saved; vector index requires rebuild")
        return {}
    graph=StateGraph(AuditState)
    for name,fn in [("monitor",monitor),("extractor",extractor),("translation",translator),("parse",parser),("completeness",completeness),("business",business),("reporting",reporting),("indexing",indexing)]: graph.add_node(name,fn)
    graph.add_edge(START,"monitor"); graph.add_edge("monitor","extractor")
    for a,b in zip(["extractor","translation","parse","completeness","business","reporting"],["translation","parse","completeness","business","reporting","indexing"]): graph.add_edge(a,b)
    graph.add_edge("indexing",END)
    return graph.compile(checkpointer=checkpointer)

async def process(path,checkpointer):
    path=Path(path).resolve()
    if not path.is_relative_to(settings.incoming.resolve()): raise ValueError("Path outside incoming folder")
    checksum=hashlib.sha256(path.read_bytes()).hexdigest()
    invoice_id,fresh=repo.detect(path,checksum)
    if not fresh: return {"invoice_id":invoice_id,"duplicate":True}
    await execute(invoice_id,checkpointer)
    return {"invoice_id":invoice_id,"duplicate":False}

async def execute(invoice_id,checkpointer,resume=False):
    with repo.claim(invoice_id):
        return await _execute(invoice_id,checkpointer,resume)

async def _execute(invoice_id,checkpointer,resume=False):
    row=repo.get(invoice_id)
    repo.status(invoice_id,"processing")
    try:
        async with Tools() as tools:
            graph=build_graph(tools,checkpointer)
            config={"configurable":{"thread_id":invoice_id}}
            with trace("invoice-workflow"):
                await graph.ainvoke(None if resume else {"invoice_id":invoice_id,"path":row["file_path"],"checksum":row["file_checksum"],"version":0},config=config)
    except Exception as e:
        # Do not leak prompts/credentials from provider exception messages.
        repo.status(invoice_id,"failed",type(e).__name__)
        raise

async def revalidate(invoice_id):
    with repo.claim(invoice_id):
        return await _revalidate(invoice_id)

async def _revalidate(invoice_id):
    row=repo.get(invoice_id)
    invoice=repo.effective(row)
    async with Tools() as tools:
        data_check=await tools.call("data_completeness_checker",{"invoice":invoice.model_dump(mode="json")})
        business_check=await tools.call("business_validation",{"invoice":invoice.model_dump(mode="json")})
        findings=data_check["findings"]+business_check["findings"]
        report={"invoice_id":invoice_id,"version":row["runs"][-1]["version"]+1,"findings":findings,
            "advisory_notes":[data_check["advisory"],business_check["advisory"]],
            "missing_fields":[x["field"] for x in findings if x["actual"] is None],
            "translation_confidence":float(row["translation_confidence"]),
            "recommendation":recommendation([Finding.model_validate(f) for f in findings],float(row["translation_confidence"]))}
        report["invoice"]=invoice.model_dump(mode="json")
        text=await tools.call("insight_reporter",{"evidence":report})
        report["explanation"],report["explanation_method"]=checked_explanation(report,text)
        repo.save_report(invoice_id,invoice,report,render_html(report),row["runs"][-1]["version"])
        await tools.call("vector_indexer",{"invoice_id":invoice_id})
    return report

async def watch(checkpointer):
    seen={}
    attempted={}
    settings.incoming.mkdir(parents=True,exist_ok=True)
    while True:
        for path in settings.incoming.iterdir():
            if not path.is_file() or path.name.startswith(".") or path.suffix == ".pending": continue
            stat=path.stat(); fingerprint=(stat.st_size,stat.st_mtime_ns)
            if seen.get(path)!=fingerprint:
                seen[path]=fingerprint; continue
            if attempted.get(path)==fingerprint: continue
            attempted[path]=fingerprint
            try: await process(path,checkpointer)
            except asyncio.CancelledError: raise
            except Exception: log.exception("Invoice processing failed; recorded for explicit retry")
        await asyncio.sleep(5)

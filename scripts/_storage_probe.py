"""Executed only inside the disposable verification stack; synthetic storage records only."""
import asyncio
import hashlib
import json
import os
import sys
from decimal import Decimal
import httpx
import psycopg
from psycopg.types.json import Jsonb
import redis
from agent.settings import settings
from langgraph.graph import StateGraph,START,END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from typing import TypedDict
ID="11111111-1111-4111-8111-111111111111"
POINT="22222222-2222-4222-8222-222222222222"
THREAD="synthetic-storage-verification"
RAW="SYNTHETIC STORAGE TEST ONLY - not an LLM invoice audit"
CACHE="storage-test:disposable"
class ProbeState(TypedDict):counter:int

def checkpoint_url():
    return settings.database_url+("&" if "?" in settings.database_url else "?")+"options=-csearch_path%3Dlanggraph"
async def checkpoint(mode):
    async with AsyncPostgresSaver.from_conn_string(checkpoint_url()) as saver:
        config={"configurable":{"thread_id":THREAD}}
        if mode=="seed":
            graph=StateGraph(ProbeState)
            graph.add_node("increment",lambda s:{"counter":s["counter"]+1})
            graph.add_edge(START,"increment");graph.add_edge("increment",END)
            await graph.compile(checkpointer=saver).ainvoke({"counter":1},config=config)
        saved=await saver.aget(config)
        if mode=="empty":assert saved is None,"Checkpoint unexpectedly survived volume deletion"
        else:assert saved["channel_values"]["counter"]==2,"Durable checkpoint missing"

def run(mode):
    assert mode in ("seed","retained","empty")
    with psycopg.connect(settings.database_url) as c:
        if mode=="seed":
            assert c.execute("SELECT count(*) FROM audit.invoice_audit").fetchone()[0]==0,"Verification DB must start empty"
            c.execute("""INSERT INTO audit.invoice_audit(invoice_id,file_path,file_checksum,raw_extracted_text,translated_text,source_language,
                translation_confidence,invoice_number,currency,total_amount,status,extracted_raw,thread_id)
                VALUES (%s,%s,%s,%s,%s,'en',1,'SYNTHETIC-PERSISTENCE-TEST','EUR',100,'test-only',%s,%s)""",
                (ID,"synthetic://storage-probe",hashlib.sha256(RAW.encode()).hexdigest(),RAW,RAW,Jsonb({"test_only":True}),THREAD))
            c.execute("INSERT INTO audit.invoice_line_items(invoice_id,line_number,item_code,quantity,unit_price,line_total) VALUES (%s,1,'TEST-SKU',1,100,100)",(ID,))
            c.execute("INSERT INTO audit.audit_runs(invoice_id,version,effective_input,report,html) VALUES (%s,1,%s,%s,%s)",
                (ID,Jsonb({"test_only":True}),Jsonb({"test_only":True,"recommendation":"review","explanation":"Synthetic storage probe; no model validation"}),"<p>Synthetic storage probe only</p>"))
            c.execute("""INSERT INTO audit.human_feedback(invoice_id,field_name,original_value,corrected_value,corrected_by,reason)
                VALUES (%s,'total_amount','100','101','automated-storage-test','Synthetic storage probe')""",(ID,))
        elif mode=="retained":
            row=c.execute("SELECT raw_extracted_text,total_amount FROM audit.invoice_audit WHERE invoice_id=%s",(ID,)).fetchone()
            assert row==(RAW,Decimal("100.00")),"Audit record or raw text lost"
            assert c.execute("SELECT count(*) FROM audit.invoice_line_items WHERE invoice_id=%s",(ID,)).fetchone()[0]==1
            assert c.execute("SELECT count(*) FROM audit.audit_runs WHERE invoice_id=%s",(ID,)).fetchone()[0]==1
            assert c.execute("SELECT corrected_value FROM audit.human_feedback WHERE invoice_id=%s",(ID,)).fetchone()[0]=="101"
        else:
            for table in ("invoice_audit","invoice_line_items","audit_runs","human_feedback"):
                assert c.execute("SELECT count(*) FROM audit."+table).fetchone()[0]==0,"Audit data unexpectedly survived deleted volumes"
    asyncio.run(checkpoint(mode))
    url=settings.qdrant_url+"/collections/invoice_chunks/points"
    if mode=="seed":
        response=httpx.put(url,params={"wait":"true"},json={"points":[{"id":POINT,"vector":[1.0]+[0.0]*1023,
            "payload":{"invoice_id":ID,"test_only":True,"chunk_text":RAW}}]},timeout=20)
        response.raise_for_status()
    response=httpx.get(url+"/"+POINT,timeout=20)
    if mode=="empty":assert response.status_code==404,"Vector unexpectedly survived deleted volume"
    else:
        response.raise_for_status();assert response.json()["result"]["payload"]["chunk_text"]==RAW
    cache=redis.Redis.from_url(settings.redis_url)
    if mode=="seed":cache.setex(CACHE,3600,"synthetic")
    else:assert cache.get(CACHE) is None,"Redis should be disposable across container recreation"
    # Respect the ERP boundary even in verification: query its HTTP API, not ERP SQL.
    po=httpx.get(settings.erp_url+"/po/PO-1001",timeout=15);po.raise_for_status()
    assert len(po.json()["line_items"])==2
    print(json.dumps({"phase":mode,"passed":True,"test_data_only":True}))
if __name__=="__main__":run(sys.argv[1])

"""Offline integration: real LangGraph/SQLite/HTTP transport, explicit test-only model replies."""
import json
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal
import httpx
from agent.models import Correction
from agent.groq_client import ProviderError
from local_dev.store import Store
from local_dev.engine import Engine
from local_dev.erp import po,vendor,sku
from test_validation import fixture

class FakeModel:
    def __init__(self): self.calls=[];self.fail_report=False;self.low_score=False;self.cite=True
    def __call__(self,system,data,**kwargs):
        self.calls.append(system)
        if "Detect the source language" in system:
            return json.dumps({"text":data,"confidence":0.99,"language":"en","notes":"test fixture"})
        if "You extract invoice data" in system: return fixture().model_dump_json()
        if "Rank evidence" in system:
            return json.dumps({"ordered_ids":[c["id"] for c in json.loads(data)["chunks"]]})
        if "Evaluate the answer" in system:
            value=0.7 if self.low_score else 0.95
            return json.dumps({"answer_relevance":value,"context_relevance":value,"groundedness":value,"reason":"test-only score"})
        if "Answer the question" in system:
            chunk=json.loads(data)["evidence"][0]["chunk_id"]
            return "The invoice totals EUR 1210.00"+(" ["+chunk+"]" if self.cite else "")
        if self.fail_report: raise ProviderError("Simulated unavailable model")
        return "Test-only report explanation; verify the numeric findings."

def erp_handler(r):
    try:
        key=r.url.path.split("/")[-1]
        value=po(key) if "/po/" in r.url.path else vendor(key) if "/vendor/" in r.url.path else sku(key)
        return httpx.Response(200,json=value)
    except Exception: return httpx.Response(404)

class LocalFlowTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/".local/test-work";base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.tmp.name)
        self.path=self.root/"invoice.pdf"; self.path.write_bytes(b"test-only-invoice-content")
        self.store=Store(self.root/"audit.db");self.model=FakeModel();self.extractions=[]
        def extract(path): self.extractions.append(path); return {"text":"English test invoice","method":"test-only-parser"}
        self.engine=Engine(self.store,"http://mock-erp",self.model,extract,httpx.MockTransport(erp_handler))
    def tearDown(self):
        assert self.root.resolve().is_relative_to(Path(__file__).resolve().parents[1]/".local/test-work")
        self.tmp.cleanup()
    def process(self): return self.engine.process(self.path)["invoice_id"]
    def test_full_workflow_and_durable_restart(self):
        id=self.process(); row=Store(self.store.path).get(id)
        self.assertEqual(row["status"],"completed");self.assertEqual(row["runs"][0]["report"]["recommendation"],"approve")
        self.assertEqual(row["stages"],["extraction","translation","parsing","validation","reporting","indexing"])
        with self.store.connect() as c: self.assertEqual(c.execute("SELECT count(*) FROM lines").fetchone()[0],2)
    def test_renamed_duplicate_not_reprocessed(self):
        id=self.process(); copy=self.root/"renamed.pdf";copy.write_bytes(self.path.read_bytes())
        result=self.engine.process(copy)
        self.assertTrue(result["duplicate"]);self.assertEqual(result["invoice_id"],id);self.assertEqual(len(self.extractions),1)
    def test_correction_preserves_original_and_versions(self):
        id=self.process()
        correction=Correction(field="unit_price",line_number=1,value="120",reviewer="Tester",reason="Fix OCR error",expected_version=1)
        report=self.engine.revalidate(id,correction);row=self.store.get(id)
        self.assertEqual(report["version"],2);self.assertEqual(len(row["runs"]),2)
        self.assertEqual(row["original"]["line_items"][0]["unit_price"],"100")
        self.assertEqual(self.store.effective(row).line_items[0].unit_price,Decimal("120"))
        self.assertTrue(row["feedback"][0]["revalidated"])
        with self.store.connect() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT DISTINCT version FROM chunks")],[2])
    def test_resume_does_not_repeat_expensive_extraction(self):
        self.model.fail_report=True
        with self.assertRaises(ProviderError): self.engine.process(self.path)
        id=self.store.list()[0]["id"];self.assertEqual(self.store.get(id)["status"],"failed")
        self.model.fail_report=False;self.engine.resume(id)
        self.assertEqual(len(self.extractions),1);self.assertEqual(self.store.get(id)["status"],"completed")
    def test_pending_correction_survives_model_failure(self):
        id=self.process();self.model.fail_report=True
        correction=Correction(field="unit_price",line_number=1,value="120",reviewer="Tester",reason="Fix OCR error",expected_version=1)
        with self.assertRaises(ProviderError): self.engine.revalidate(id,correction)
        self.assertFalse(self.store.get(id)["feedback"][0]["revalidated"])
        self.model.fail_report=False;self.engine.revalidate(id)
        self.assertTrue(self.store.get(id)["feedback"][0]["revalidated"])
    def test_rag_answer_citations_and_cache(self):
        id=self.process();first=self.engine.question("Explain this invoice",id)
        calls=len(self.model.calls);second=self.engine.question("Explain this invoice",id)
        self.assertTrue(first["accepted"]);self.assertTrue(second["cached"]);self.assertEqual(len(self.model.calls),calls)
    def test_exact_point_seven_is_rejected_after_four_attempts(self):
        id=self.process();self.model.low_score=True
        result=self.engine.question("Explain this invoice",id)
        self.assertFalse(result["accepted"]);self.assertEqual(result["attempts"],4)
    def test_answer_without_citation_is_rejected(self):
        id=self.process();self.model.cite=False
        self.assertFalse(self.engine.question("Explain this invoice",id)["accepted"])
    def test_invoice_scope_does_not_leak(self):
        self.process()
        result=self.engine.question("Explain this invoice","different-id")
        self.assertFalse(result["accepted"]);self.assertEqual(result["attempts"],0)
    def test_structured_total_does_not_call_model(self):
        id=self.process();calls=len(self.model.calls)
        self.assertEqual(self.engine.question("What is the total?",id)["route"],"sql")
        self.assertEqual(len(self.model.calls),calls)
    def test_stale_correction_rejected(self):
        id=self.process()
        correction=Correction(field="currency",value="EUR",reviewer="Tester",reason="Fix currency",expected_version=5)
        with self.assertRaisesRegex(ValueError,"Report changed"): self.engine.revalidate(id,correction)
    def test_rebuild_requires_neither_file_nor_model(self):
        id=self.process();self.path.unlink();calls=len(self.model.calls)
        self.engine.index(id)
        self.assertEqual(len(self.model.calls),calls)

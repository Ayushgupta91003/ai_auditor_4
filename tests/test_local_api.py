import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from local_dev import main
from local_dev.engine import Engine
from local_dev.store import Store
from test_local_flow import FakeModel,erp_handler
from local_dev.preflight import loopback_status
SOCKET_OK,SOCKET_MESSAGE=loopback_status()

@unittest.skipUnless(SOCKET_OK,SOCKET_MESSAGE)
class LocalApiTests(unittest.TestCase):
    def setUp(self):
        base=Path(__file__).resolve().parents[1]/".local/test-work";base.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.tmp.name)
        store=Store(self.root/"test.db")
        engine=Engine(store,"http://mock-erp",FakeModel(),lambda p:{"text":"English fixture invoice","method":"test-only"},httpx.MockTransport(erp_handler))
        self.patches=[patch.object(main,"store",store),patch.object(main,"engine",engine),patch.object(main,"INCOMING",self.root/"incoming"),patch.dict(os.environ,{"GROQ_API_KEY":""})]
        for p in self.patches:p.start()
        self.client=TestClient(main.app,base_url="http://127.0.0.1");self.client.__enter__()
        self.headers={"Authorization":"Bearer "+main.TOKEN}
    def tearDown(self):
        self.client.__exit__(None,None,None)
        for p in reversed(self.patches):p.stop()
        assert self.root.resolve().is_relative_to(Path(__file__).resolve().parents[1]/".local/test-work")
        self.tmp.cleanup()
    def upload(self):
        r=self.client.post("/api/upload",headers=self.headers,files={"file":("invoice.pdf",b"test-api-only","application/pdf")})
        self.assertEqual(r.status_code,200,r.text);return r.json()["invoice_id"]
    def test_dashboard_no_key_status(self):
        self.assertEqual(self.client.get("/").status_code,200)
        r=self.client.get("/api/status",headers=self.headers)
        self.assertFalse(r.json()["key_configured"]);self.assertNotIn("GROQ_API_KEY",r.text)
    def test_api_requires_session_token(self):self.assertEqual(self.client.get("/api/invoices").status_code,401)
    def test_host_header_protection(self):self.assertEqual(self.client.get("/",headers={"Host":"untrusted.invalid"}).status_code,400)
    def test_upload_report_question(self):
        id=self.upload()
        r=self.client.get("/api/invoices/"+id,headers=self.headers)
        self.assertEqual(r.json()["runs"][0]["report"]["recommendation"],"approve")
        download=self.client.get(f"/api/invoices/{id}/download/1/html",headers=self.headers)
        self.assertIn("Invoice audit",download.text);self.assertIn("attachment",download.headers["content-disposition"])
        q=self.client.post("/api/questions",headers=self.headers,json={"question":"Why was it flagged?","invoice_id":id})
        self.assertTrue(q.json()["accepted"])
    def test_bad_extension(self):
        r=self.client.post("/api/upload",headers=self.headers,files={"file":("bad.exe",b"bad")})
        self.assertEqual(r.status_code,400)
    def test_empty_file(self):
        r=self.client.post("/api/upload",headers=self.headers,files={"file":("empty.pdf",b"")})
        self.assertEqual(r.status_code,400)
    def test_invalid_uuid(self):self.assertEqual(self.client.get("/api/invoices/bad",headers=self.headers).status_code,422)
    def test_correction_versions(self):
        id=self.upload()
        correction={"field":"unit_price","line_number":1,"value":"120","reviewer":"Tester","reason":"Fix OCR","expected_version":1}
        r=self.client.post(f"/api/invoices/{id}/corrections",headers=self.headers,json=correction)
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()["version"],2)
        row=self.client.get("/api/invoices/"+id,headers=self.headers).json()
        self.assertEqual(row["original"]["line_items"][0]["unit_price"],"100");self.assertEqual(len(row["runs"]),2)

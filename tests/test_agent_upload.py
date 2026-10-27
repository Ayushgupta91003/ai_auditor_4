"""Reject invalid uploads before persistence or model work in the final API."""
import importlib.util
import io
import unittest

FULL = all(importlib.util.find_spec(name) is not None for name in ("a2a", "google.adk", "psycopg_pool", "qdrant_client"))

@unittest.skipUnless(FULL, "Full agent requirements needed for final API boundary checks")
class AgentUploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_upload_rejected_before_processing(self):
        from fastapi import HTTPException, UploadFile
        from agent.main import upload
        with self.assertRaises(HTTPException) as caught:
            await upload(UploadFile(filename="empty.pdf", file=io.BytesIO(b"")))
        self.assertEqual(caught.exception.status_code, 400)

    async def test_unsupported_file_rejected_before_processing(self):
        from fastapi import HTTPException, UploadFile
        from agent.main import upload
        with self.assertRaises(HTTPException) as caught:
            await upload(UploadFile(filename="bad.exe", file=io.BytesIO(b"test")))
        self.assertEqual(caught.exception.status_code, 400)

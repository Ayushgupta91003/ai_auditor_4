import unittest
from pathlib import Path
from unittest.mock import patch
from local_dev.documents import extract
ROOT=Path(__file__).resolve().parents[1]
class LocalDocumentTests(unittest.TestCase):
    def test_english_pdf_direct_text(self):
        result=extract(ROOT/"samples/english.pdf")
        self.assertEqual(result["method"],"pymupdf");self.assertIn("INV-ENGLISH-001",result["text"])
    def test_spanish_docx_direct_text(self):
        result=extract(ROOT/"samples/spanish.docx")
        self.assertEqual(result["method"],"docx");self.assertIn("1430",result["text"])
    def test_german_pdf_direct_text(self):
        self.assertIn("Rechnungsnummer",extract(ROOT/"samples/german.pdf")["text"])
    def test_scanned_pdf_routes_to_image_transcription(self):
        with patch("local_dev.documents.image_text",return_value=("OCR test text","test-only-ocr")) as ocr:
            result=extract(ROOT/"samples/german-scanned.pdf")
        self.assertTrue(ocr.called);self.assertEqual(result["method"],"test-only-ocr")
        self.assertTrue(ocr.call_args.args[0].startswith(b"\x89PNG"))
    def test_png_routes_to_image_transcription(self):
        with patch("local_dev.documents.image_text",return_value=("OCR test text","test-only-ocr")):
            self.assertEqual(extract(ROOT/"samples/german.png")["method"],"test-only-ocr")
    def test_unsupported_format_rejected(self):
        with self.assertRaisesRegex(ValueError,"Supported"):
            extract(ROOT/"samples/english.txt")

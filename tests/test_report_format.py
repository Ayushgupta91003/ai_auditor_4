import unittest
from agent.report_format import render_html
from test_validation import fixture
class ReportExportTests(unittest.TestCase):
    def report(self):return {"invoice":fixture().model_dump(mode="json"),"version":2,"findings":[],"missing_fields":[],"recommendation":"approve","translation_confidence":1,"explanation":"Configured checks found no discrepancies."}
    def test_header_line_items_and_empty_findings(self):
        html=render_html(self.report())
        for expected in ("INV-001","PO-1001","BOX-01","PAL-01","1210","No discrepancies found"):
            self.assertIn(expected,html)
    def test_html_escapes_untrusted_strings(self):
        r=self.report();r["explanation"]="<script>alert(1)</script>"
        html=render_html(r);self.assertNotIn("<script>",html);self.assertIn("&lt;script&gt;",html)
    def test_legacy_report_still_downloads(self):
        r=self.report();del r["invoice"]
        self.assertIn("Invoice audit",render_html(r))

import json
import unittest
from agent.rag_evidence import report_evidence
class ReportEvidenceTests(unittest.TestCase):
    def test_model_prose_and_internal_profile_not_used_as_evidence(self):
        report={"invoice_id":"test","version":2,"findings":[],"recommendation":"review","explanation":"Wrong $120","profile":"internal deployment detail"}
        value=report_evidence(report,{"currency":"EUR","total_amount":"1430"})
        self.assertNotIn("Wrong $120",value);self.assertNotIn("internal deployment",value)
        self.assertEqual(json.loads(value)["invoice"]["currency"],"EUR")
    def test_effective_snapshot_used_without_mutating_original_report(self):
        report={"invoice":{"unit_price":"120"},"findings":[],"recommendation":"review"}
        value=json.loads(report_evidence(report,{"unit_price":"100"}))
        self.assertEqual(value["invoice"]["unit_price"],"100")
        self.assertEqual(report["invoice"]["unit_price"],"120")

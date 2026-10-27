import unittest
from agent.report_explanation import checked_explanation
class CurrencyExplanationTests(unittest.TestCase):
    def report(self):return {"invoice":{"invoice_number":"INV-ES-001","currency":"EUR"},"recommendation":"review","findings":[{"field":"unit_price","line_number":1,"actual":"120","expected":"100","deviation_percent":"20","message":"ERP mismatch"}]}
    def test_dollar_hallucination_falls_back_to_verified_euros(self):
        text,method=checked_explanation(self.report(),"Invoice price is $120 instead of $100")
        self.assertEqual(method,"verified-findings-template");self.assertIn("EUR 120",text);self.assertNotIn("$",text)
    def test_valid_currency_prose_preserved(self):
        original="Invoice price EUR 120 differs from EUR 100."
        self.assertEqual(checked_explanation(self.report(),original),(original,"model"))
    def test_real_currency_mismatch_can_mention_both(self):
        r=self.report();r["findings"]=[{"field":"currency","actual":"EUR","expected":"USD","message":"Currency mismatch"}]
        self.assertEqual(checked_explanation(r,"Invoice EUR differs from PO USD")[1],"model")

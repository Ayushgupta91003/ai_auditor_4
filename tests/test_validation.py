import unittest
from unittest.mock import patch
from decimal import Decimal
import httpx
from agent.models import Invoice
from agent.validation import completeness,business,recommendation

def fixture():
    return Invoice.model_validate({"invoice_number":"INV-001","invoice_date":"2026-10-01","vendor_name":"Global Logistics Supplies",
        "vendor_id":"V001","po_number":"PO-1001","currency":"EUR","subtotal":"1100","tax_rate":"10","tax_amount":"110","total_amount":"1210",
        "line_items":[{"line_number":1,"item_code":"BOX-01","quantity":"10","unit_price":"100","line_total":"1000"},
        {"line_number":2,"item_code":"PAL-01","quantity":"2","unit_price":"50","line_total":"100"}]})
class ValidationTests(unittest.TestCase):
    def test_matching(self): self.assertEqual(completeness(fixture()),[])
    def test_line_arithmetic(self):
        i=fixture(); i.line_items[0].unit_price=Decimal("120")
        self.assertIn("line_total",[f.field for f in completeness(i)])
    def test_zero_not_missing(self):
        i=fixture(); i.total_amount=Decimal(0)
        self.assertFalse(any(f.field=="total_amount" and f.actual is None for f in completeness(i)))
    def test_missing_required(self):
        i=fixture(); i.po_number=None
        self.assertTrue(any(f.field=="po_number" for f in completeness(i)))
    def test_bad_tax(self):
        i=fixture(); i.tax_amount=Decimal("100")
        self.assertIn("tax_amount",[f.field for f in completeness(i)])
    def test_erp_http_price_tolerance(self):
        requests=[]
        def handler(r):
            requests.append(str(r.url))
            if r.url.path.startswith("/po/"): data={"vendor_id":"V001","currency":"EUR","line_items":[{"item_code":"BOX-01","quantity":"10","unit_price":"100"},{"item_code":"PAL-01","quantity":"2","unit_price":"50"}]}
            elif r.url.path.startswith("/vendor/"): data={"name":"Global Logistics Supplies"}
            else: data={"item_code":r.url.path.split("/")[-1]}
            return httpx.Response(200,json=data)
        client=httpx.Client(base_url="http://mock-erp:8000",transport=httpx.MockTransport(handler))
        i=fixture(); i.line_items[0].unit_price=Decimal("102")
        with patch("agent.validation.httpx.Client",return_value=client): findings=business(i,"http://mock-erp:8000")
        price=next(f for f in findings if f.field=="unit_price")
        self.assertEqual(Decimal(price.deviation_percent),Decimal("2")); self.assertEqual(price.line_number,1)
        self.assertEqual(len(requests),4)
    def test_reject_high_deviation(self):
        from agent.models import Finding
        findings=[Finding(rule_id="test",field="unit_price",severity="reject",message="High deviation")]
        self.assertEqual(recommendation(findings,1),"reject")
    def test_unknown_po(self):
        client=httpx.Client(base_url="http://mock-erp:8000",transport=httpx.MockTransport(lambda r:httpx.Response(404)))
        with patch("agent.validation.httpx.Client",return_value=client): f=business(fixture(),"http://mock-erp:8000")
        self.assertEqual(recommendation(f,1),"review")
    def test_low_confidence(self): self.assertEqual(recommendation([],0.5),"review")
    def test_decimal_cents(self):
        i=fixture(); i.line_items=i.line_items[:1]; l=i.line_items[0]
        l.quantity=Decimal(3); l.unit_price=Decimal("0.10"); l.line_total=Decimal("0.30")
        i.subtotal=Decimal("0.30"); i.tax_rate=Decimal(0); i.tax_amount=Decimal(0); i.total_amount=Decimal("0.30")
        self.assertEqual(completeness(i),[])
if __name__=="__main__": unittest.main()

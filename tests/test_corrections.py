import unittest
from copy import deepcopy
from decimal import Decimal
from agent.corrections import apply_feedback,prepare_correction
from agent.models import Correction
from test_validation import fixture

class CorrectionTests(unittest.TestCase):
    def test_feedback_does_not_mutate_original(self):
        raw=fixture().model_dump(mode="json"); before=deepcopy(raw)
        effective=apply_feedback(raw,[{"field_name":"unit_price","line_number":1,"corrected_value":'"90"'}])
        self.assertEqual(effective.line_items[0].unit_price,Decimal("90"))
        self.assertEqual(raw,before)
    def test_latest_feedback_wins(self):
        raw=fixture().model_dump(mode="json")
        changes=[{"field_name":"unit_price","line_number":1,"corrected_value":'"90"'},
                 {"field_name":"unit_price","line_number":1,"corrected_value":'"95"'}]
        self.assertEqual(apply_feedback(raw,changes).line_items[0].unit_price,Decimal("95"))
    def test_invalid_line_rejected(self):
        with self.assertRaisesRegex(ValueError,"Line number"):
            apply_feedback(fixture().model_dump(mode="json"),[{"field_name":"unit_price","line_number":99,"corrected_value":'"90"'}])
    def test_invalid_currency_rejected(self):
        correction=Correction(field="currency",value="EURO",reviewer="Tester",reason="Correct currency",expected_version=1)
        with self.assertRaises(ValueError): prepare_correction(fixture(),correction)
    def test_prepare_validated_decimal_and_original(self):
        invoice=fixture()
        c=Correction(field="unit_price",value="99.50",line_number=1,reviewer="Tester",reason="Fix OCR",expected_version=1)
        original,corrected=prepare_correction(invoice,c)
        self.assertEqual(original,'"100"'); self.assertEqual(corrected,'"99.50"')
        self.assertEqual(invoice.line_items[0].unit_price,Decimal("100"))
    def test_unextracted_invoice_rejected(self):
        with self.assertRaisesRegex(ValueError,"not been extracted"):
            apply_feedback(None,[])

"""
LangGraph Workflow State Definition
Holds the complete working memory of an invoice audit run.
"""

from typing import Dict, Any, List, Optional
from typing_extensions import TypedDict

class InvoiceLineItem(TypedDict):
    line_number: int
    item_code: Optional[str]
    description: Optional[str]
    quantity: float
    unit_price: float
    line_total: float

class Discrepancy(TypedDict):
    field_name: str
    invoice_value: Any
    erp_value: Any
    deviation_pct: float
    severity: str

class InvoiceState(TypedDict):
    # Ingestion & Detection
    file_path: str
    file_checksum: str
    metadata: Dict[str, Any]
    skipped: bool
    skip_reason: Optional[str]

    # Extraction
    extraction_method: str
    raw_extracted_text: str

    # Translation
    source_language: str
    language_name: str
    translated_text: str
    translation_confidence: float

    # Parsing
    invoice_number: Optional[str]
    invoice_date: Optional[str]
    vendor_id: Optional[str]
    vendor_name: Optional[str]
    po_number: Optional[str]
    currency: Optional[str]
    subtotal: Optional[float]
    tax_amount: Optional[float]
    total_amount: Optional[float]
    line_items: List[Dict[str, Any]]
    extracted_raw: Dict[str, Any]

    # Validation
    data_validation_passed: bool
    data_validation_errors: List[str]
    business_validation_passed: bool
    discrepancies: List[Dict[str, Any]]
    validation_status: str        # 'passed', 'failed', 'partial'
    recommendation: str           # 'approve', 'manual_review', 'reject'

    # Human-in-the-loop review gate
    risk_score: float
    review_status: str            # 'auto_approved', 'pending_review', 'approved', 'rejected'

    # Reporting & Indexing
    report_json_path: Optional[str]
    report_html_path: Optional[str]
    invoice_id: Optional[str]
    thread_id: Optional[str]
    rag_indexed: bool
    error: Optional[str]

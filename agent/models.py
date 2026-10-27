"""Shared typed contracts; member 2 owns schema changes."""
from datetime import date
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class LineItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    line_number: int = Field(ge=1)
    item_code: str | None = None
    description: str = ''
    quantity: Decimal | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    line_total: Decimal | None = Field(default=None, ge=0)

class Invoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    extra_fields: dict[str, str] = Field(default_factory=dict)
    invoice_number: str | None = None
    invoice_date: date | None = None
    vendor_name: str | None = None
    vendor_id: str | None = None
    po_number: str | None = None
    currency: str | None = Field(default=None, pattern=r'^[A-Z]{3}$')
    subtotal: Decimal | None = Field(default=None, ge=0)
    tax_rate: Decimal | None = Field(default=None, ge=0, le=100)
    tax_amount: Decimal | None = Field(default=None, ge=0)
    freight: Decimal = Field(default=Decimal('0'), ge=0)
    discount: Decimal = Field(default=Decimal('0'), ge=0)
    total_amount: Decimal | None = Field(default=None, ge=0)
    line_items: list[LineItem] = Field(default_factory=list)

class Finding(BaseModel):
    rule_id: str
    field: str
    actual: str | None = None
    expected: str | None = None
    deviation_percent: str | None = None
    severity: Literal['review', 'reject'] = 'review'
    message: str
    line_number: int | None = None

class Correction(BaseModel):
    field: str
    value: str
    line_number: int | None = Field(default=None, ge=1)
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=1000)
    expected_version: int = Field(ge=1)

class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    invoice_id: str | None = None

"""
FastAPI Mock ERP Service
Provides endpoints to query Purchase Orders, Vendors, and SKUs.
Addresses requirement 3.4: "Calls the mock ERP service over HTTP by service name."
"""

import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from .db import erp_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("mock_erp_api")

app = FastAPI(
    title="Mock ERP API Service",
    description="Simulated enterprise ERP system providing master records for POs, Vendors, and SKUs",
    version="1.0.0"
)

# ------------------------------------------------------------------------------
# Pydantic Schemas
# ------------------------------------------------------------------------------
class POLineItem(BaseModel):
    item_code: str
    description: Optional[str] = None
    qty: float
    unit_price: float
    currency: str

class PurchaseOrderResponse(BaseModel):
    po_number: str
    vendor_id: str
    created_at: Optional[str] = None
    line_items: List[POLineItem]

class VendorResponse(BaseModel):
    vendor_id: str
    vendor_name: str
    country: Optional[str] = None
    currency: str

class SKUResponse(BaseModel):
    item_code: str
    category: Optional[str] = None
    uom: Optional[str] = None
    gst_rate: float = 0.0

class HealthResponse(BaseModel):
    status: str
    service: str
    backend: str

# ------------------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
def health_check():
    return {
        "status": "healthy",
        "service": "mock-erp",
        "backend": "postgresql" if erp_db.use_postgres else "json_cache"
    }

@app.get("/po/{po_number}", response_model=PurchaseOrderResponse)
def get_purchase_order(po_number: str):
    logger.info(f"Looking up PO: {po_number}")
    po = erp_db.get_po(po_number)
    if not po:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Purchase Order '{po_number}' not found in ERP records."
        )
    return po

@app.get("/vendor/{vendor_id}", response_model=VendorResponse)
def get_vendor(vendor_id: str):
    logger.info(f"Looking up Vendor: {vendor_id}")
    vendor = erp_db.get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor '{vendor_id}' not found in ERP records."
        )
    return vendor

@app.get("/sku/{sku_code}", response_model=SKUResponse)
def get_sku(sku_code: str):
    logger.info(f"Looking up SKU: {sku_code}")
    sku = erp_db.get_sku(sku_code)
    if not sku:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SKU code '{sku_code}' not found in master records."
        )
    return sku

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

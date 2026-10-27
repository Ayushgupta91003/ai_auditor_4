import os
from contextlib import asynccontextmanager
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException

def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
@asynccontextmanager
async def lifespan(app):
    with connect() as conn: conn.execute("SELECT 1 FROM erp.vendors LIMIT 1")
    yield
app = FastAPI(title="Mock ERP - synthetic fixtures", lifespan=lifespan)
@app.get("/health")
def health():
    with connect() as conn: conn.execute("SELECT 1")
    return {"status":"ok"}
@app.get("/po/{po_number}")
def po(po_number: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM erp.purchase_orders WHERE po_number=%s", (po_number,)).fetchone()
        if not row: raise HTTPException(404, "PO not found")
        row["line_items"] = conn.execute("SELECT item_code,quantity,unit_price FROM erp.po_line_items WHERE po_number=%s", (po_number,)).fetchall()
        return row
@app.get("/vendor/{vendor_id}")
def vendor(vendor_id: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM erp.vendors WHERE vendor_id=%s", (vendor_id,)).fetchone()
        if not row: raise HTTPException(404, "Vendor not found")
        return row
@app.get("/sku/{sku_code}")
def sku(sku_code: str):
    with connect() as conn:
        row = conn.execute("SELECT * FROM erp.sku_master WHERE item_code=%s", (sku_code,)).fetchone()
        if not row: raise HTTPException(404, "SKU not found")
        return row

"""Local HTTP mock ERP; invoice business checks still cross an HTTP boundary."""
from fastapi import APIRouter,HTTPException
router=APIRouter()
@router.get("/po/{po_number}")
def po(po_number:str):
    if po_number!="PO-1001": raise HTTPException(404,"PO not found")
    return {"po_number":po_number,"vendor_id":"V001","currency":"EUR","line_items":[
        {"item_code":"BOX-01","quantity":"10","unit_price":"100"},
        {"item_code":"PAL-01","quantity":"2","unit_price":"50"}]}
@router.get("/vendor/{vendor_id}")
def vendor(vendor_id:str):
    if vendor_id!="V001": raise HTTPException(404,"Vendor not found")
    return {"vendor_id":vendor_id,"name":"Global Logistics Supplies"}
@router.get("/sku/{sku_code}")
def sku(sku_code:str):
    if sku_code not in ("BOX-01","PAL-01"): raise HTTPException(404,"SKU not found")
    return {"item_code":sku_code,"description":"Shipping boxes" if sku_code=="BOX-01" else "Wooden pallets"}

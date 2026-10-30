"""
Database access layer for Mock ERP Service.
Queries the 'erp' schema in PostgreSQL, with an in-memory/JSON fallback for local testing.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger("mock_erp")

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MOCK_DATA_DIR = BASE_DIR / "data" / "ERP_mockdata"
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://auditor:auditor_secret@postgres:5432/invoice_db")

class ERPDatabase:
    def __init__(self):
        self.use_postgres = False
        self.pool = None
        self._local_cache = {"vendors": {}, "skus": {}, "pos": {}}
        self._init_connection()

    def _init_connection(self):
        # First load JSON data into memory as fallback
        self._load_fallback_data()

        # Attempt to connect to PostgreSQL if available
        try:
            import psycopg2
            from psycopg2 import pool
            
            # If localhost or docker hostname
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
            conn.close()
            self.pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
            self.use_postgres = True
            logger.info("Connected to PostgreSQL erp schema successfully.")
        except Exception as e:
            logger.warning(f"PostgreSQL connection failed ({e}). Operating in JSON-backed local mock mode.")
            self.use_postgres = False

    def _load_fallback_data(self):
        try:
            v_path = MOCK_DATA_DIR / "vendors.json"
            if v_path.exists():
                with open(v_path, "r", encoding="utf-8") as f:
                    for v in json.load(f):
                        self._local_cache["vendors"][v["vendor_id"]] = v

            s_path = MOCK_DATA_DIR / "sku_master.json"
            if s_path.exists():
                with open(s_path, "r", encoding="utf-8") as f:
                    for s in json.load(f):
                        self._local_cache["skus"][s["item_code"]] = s

            p_path = MOCK_DATA_DIR / "PO Records.json"
            if p_path.exists():
                with open(p_path, "r", encoding="utf-8") as f:
                    for p in json.load(f):
                        self._local_cache["pos"][p["po_number"]] = p
            logger.info(f"Loaded ERP mock data into cache: {len(self._local_cache['vendors'])} vendors, {len(self._local_cache['skus'])} skus, {len(self._local_cache['pos'])} POs")
        except Exception as e:
            logger.error(f"Failed to load fallback ERP data: {e}")

    def get_po(self, po_number: str) -> Optional[Dict[str, Any]]:
        po_number = po_number.strip().upper()
        if self.use_postgres and self.pool:
            conn = None
            try:
                conn = self.pool.getconn()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT po_number, vendor_id, created_at FROM erp.purchase_orders WHERE UPPER(po_number) = %s;",
                        (po_number,)
                    )
                    header = cur.fetchone()
                    if not header:
                        return None
                    
                    cur.execute(
                        """
                        SELECT item_code, description, qty, unit_price, currency
                        FROM erp.po_line_items
                        WHERE UPPER(po_number) = %s;
                        """,
                        (po_number,)
                    )
                    rows = cur.fetchall()
                    line_items = [
                        {
                            "item_code": r[0],
                            "description": r[1],
                            "qty": float(r[2]),
                            "unit_price": float(r[3]),
                            "currency": r[4]
                        }
                        for r in rows
                    ]
                    return {
                        "po_number": header[0],
                        "vendor_id": header[1],
                        "created_at": header[2].isoformat() if header[2] else None,
                        "line_items": line_items
                    }
            except Exception as e:
                logger.error(f"DB error fetching PO {po_number}: {e}")
            finally:
                if conn:
                    self.pool.putconn(conn)

        # Fallback to local cache
        return self._local_cache["pos"].get(po_number)

    def get_vendor(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        vendor_id = vendor_id.strip().upper()
        if self.use_postgres and self.pool:
            conn = None
            try:
                conn = self.pool.getconn()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT vendor_id, vendor_name, country, currency FROM erp.vendors WHERE UPPER(vendor_id) = %s;",
                        (vendor_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        return {
                            "vendor_id": row[0],
                            "vendor_name": row[1],
                            "country": row[2],
                            "currency": row[3]
                        }
                    return None
            except Exception as e:
                logger.error(f"DB error fetching vendor {vendor_id}: {e}")
            finally:
                if conn:
                    self.pool.putconn(conn)

        return self._local_cache["vendors"].get(vendor_id)

    def get_sku(self, item_code: str) -> Optional[Dict[str, Any]]:
        item_code = item_code.strip().upper()
        if self.use_postgres and self.pool:
            conn = None
            try:
                conn = self.pool.getconn()
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT item_code, category, uom, gst_rate FROM erp.sku_master WHERE UPPER(item_code) = %s;",
                        (item_code,)
                    )
                    row = cur.fetchone()
                    if row:
                        return {
                            "item_code": row[0],
                            "category": row[1],
                            "uom": row[2],
                            "gst_rate": float(row[3]) if row[3] is not None else 0.0
                        }
                    return None
            except Exception as e:
                logger.error(f"DB error fetching SKU {item_code}: {e}")
            finally:
                if conn:
                    self.pool.putconn(conn)

        return self._local_cache["skus"].get(item_code)

erp_db = ERPDatabase()

"""
Database Seeding Script for ERP Master Data
Reads from data/ERP_mockdata/*.json and populates the erp schema in PostgreSQL.
Also supports SQLite fallback for local stand-alone mode.
"""

import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data" / "ERP_mockdata"

def load_json(filename: str):
    path = DATA_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Mock data file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def seed_postgres(connection_string: str = None):
    try:
        import psycopg2
        from psycopg2.extras import execute_batch
    except ImportError:
        logger.warning("psycopg2 not installed. Skipping direct postgres seeding.")
        return False

    db_url = connection_string or os.getenv("DATABASE_URL", "postgresql://auditor:auditor_secret@localhost:5432/invoice_db")
    logger.info(f"Connecting to PostgreSQL: {db_url.split('@')[-1]}")
    
    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()

        # Seed vendors
        vendors = load_json("vendors.json")
        vendor_tuples = [(v["vendor_id"], v["vendor_name"], v.get("country"), v["currency"]) for v in vendors]
        execute_batch(
            cur,
            """
            INSERT INTO erp.vendors (vendor_id, vendor_name, country, currency)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (vendor_id) DO UPDATE SET
                vendor_name = EXCLUDED.vendor_name,
                country = EXCLUDED.country,
                currency = EXCLUDED.currency;
            """,
            vendor_tuples
        )
        logger.info(f"Seeded {len(vendors)} vendors.")

        # Seed SKU Master
        skus = load_json("sku_master.json")
        sku_tuples = [(s["item_code"], s.get("category"), s.get("uom"), s.get("gst_rate", 0)) for s in skus]
        execute_batch(
            cur,
            """
            INSERT INTO erp.sku_master (item_code, category, uom, gst_rate)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (item_code) DO UPDATE SET
                category = EXCLUDED.category,
                uom = EXCLUDED.uom,
                gst_rate = EXCLUDED.gst_rate;
            """,
            sku_tuples
        )
        logger.info(f"Seeded {len(skus)} SKU items.")

        # Seed PO Records & Line Items
        pos = load_json("PO Records.json")
        for po in pos:
            cur.execute(
                """
                INSERT INTO erp.purchase_orders (po_number, vendor_id)
                VALUES (%s, %s)
                ON CONFLICT (po_number) DO UPDATE SET vendor_id = EXCLUDED.vendor_id;
                """,
                (po["po_number"], po["vendor_id"])
            )
            # Delete existing lines to avoid duplicate lines on re-seed
            cur.execute("DELETE FROM erp.po_line_items WHERE po_number = %s;", (po["po_number"],))
            lines = po.get("line_items", [])
            line_tuples = [
                (po["po_number"], l["item_code"], l.get("description"), l["qty"], l["unit_price"], l.get("currency", "USD"))
                for l in lines
            ]
            execute_batch(
                cur,
                """
                INSERT INTO erp.po_line_items (po_number, item_code, description, qty, unit_price, currency)
                VALUES (%s, %s, %s, %s, %s, %s);
                """,
                line_tuples
            )
        logger.info(f"Seeded {len(pos)} purchase orders with line items.")

        conn.commit()
        cur.close()
        conn.close()
        logger.info("Successfully completed ERP data seeding in PostgreSQL.")
        return True
    except Exception as e:
        logger.error(f"Error seeding PostgreSQL: {e}")
        return False

if __name__ == "__main__":
    seed_postgres()

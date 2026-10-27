"""Explicit SQL. Never reads erp schema; immutable extraction and report versions."""
from uuid import uuid4
import json
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from agent.settings import settings
from agent.models import Invoice
from agent.corrections import apply_feedback,prepare_correction
pool = ConnectionPool(settings.database_url, min_size=1, max_size=8, open=False,
    kwargs={"row_factory":dict_row, "connect_timeout":10})

def detect(path, checksum):
    invoice_id = str(uuid4())
    with pool.connection() as c:
        row = c.execute("""INSERT INTO audit.invoice_audit(invoice_id,file_path,file_checksum,thread_id)
            VALUES (%s,%s,%s,%s) ON CONFLICT(file_checksum) DO NOTHING RETURNING invoice_id""",
            (invoice_id,str(path),checksum,invoice_id)).fetchone()
        fresh=bool(row)
        if not fresh:
            invoice_id=str(c.execute("SELECT invoice_id FROM audit.invoice_audit WHERE file_checksum=%s",(checksum,)).fetchone()["invoice_id"])
        c.execute("INSERT INTO audit.file_events(invoice_id,file_path,file_checksum,duplicate) VALUES (%s,%s,%s,%s)",
            (invoice_id,str(path),checksum,not fresh))
        return invoice_id,fresh

def get(invoice_id):
    with pool.connection() as c:
        row = c.execute("SELECT * FROM audit.invoice_audit WHERE invoice_id=%s",(invoice_id,)).fetchone()
        if not row: raise KeyError("Invoice not found")
        row["runs"] = c.execute("SELECT * FROM audit.audit_runs WHERE invoice_id=%s ORDER BY version",(invoice_id,)).fetchall()
        row["feedback"] = c.execute("SELECT * FROM audit.human_feedback WHERE invoice_id=%s ORDER BY id",(invoice_id,)).fetchall()
        return row

def list_invoices():
    with pool.connection() as c:
        return c.execute("""SELECT invoice_id,invoice_number,vendor_name,total_amount,currency,status,error,processed_at
            FROM audit.invoice_audit ORDER BY processed_at DESC LIMIT 500""").fetchall()

def status(invoice_id, value, error=None):
    with pool.connection() as c:
        c.execute("UPDATE audit.invoice_audit SET status=%s,error=%s WHERE invoice_id=%s",(value,error,invoice_id))

def raw(invoice_id,text,method):
    with pool.connection() as c:
        c.execute("UPDATE audit.invoice_audit SET raw_extracted_text=%s,extraction_method=%s WHERE invoice_id=%s",(text,method,invoice_id))

def extracted(invoice_id,invoice,translation):
    data = invoice.model_dump(mode="json")
    with pool.connection() as c:
        existing=c.execute("SELECT extracted_raw FROM audit.invoice_audit WHERE invoice_id=%s FOR UPDATE",(invoice_id,)).fetchone()
        if existing and existing["extracted_raw"] is not None:
            return existing["extracted_raw"]
        c.execute("""UPDATE audit.invoice_audit SET extracted_raw=%s,translated_text=%s,source_language=%s,
            translation_confidence=%s,invoice_number=%s,invoice_date=%s,vendor_name=%s,vendor_id=%s,
            po_number=%s,currency=%s,total_amount=%s WHERE invoice_id=%s""",
            (Jsonb(data),translation["text"],translation["language"],translation["confidence"],invoice.invoice_number,
            invoice.invoice_date,invoice.vendor_name,invoice.vendor_id,invoice.po_number,invoice.currency,invoice.total_amount,invoice_id))
        for line in invoice.line_items:
            c.execute("""INSERT INTO audit.invoice_line_items(invoice_id,line_number,item_code,description,quantity,unit_price,line_total)
                VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(invoice_id,line_number) DO NOTHING""", (invoice_id,line.line_number,line.item_code,line.description,line.quantity,line.unit_price,line.line_total))
    return data

def effective(row):
    return apply_feedback(row["extracted_raw"],row["feedback"])


def feedback(invoice_id, correction):
    with claim(invoice_id):
        return _feedback(invoice_id,correction)

def _feedback(invoice_id, correction):
    with pool.connection() as c:
        c.execute("SELECT invoice_id FROM audit.invoice_audit WHERE invoice_id=%s FOR UPDATE",(invoice_id,))
        # A pending feedback record is not accepted twice; retries revalidate it first.
        if c.execute("SELECT 1 FROM audit.human_feedback WHERE invoice_id=%s AND NOT revalidated",(invoice_id,)).fetchone():
            raise ValueError("Revalidate pending correction first")
        row = get(invoice_id)
        if not row["runs"] or row["runs"][-1]["version"] != correction.expected_version:
            raise ValueError("Stale report version; refresh before correcting")
        original,corrected=prepare_correction(effective(row),correction)
        c.execute("""INSERT INTO audit.human_feedback(invoice_id,field_name,line_number,original_value,corrected_value,corrected_by,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",(invoice_id,correction.field,correction.line_number,original,corrected,correction.reviewer,correction.reason))

def save_report(invoice_id,invoice,report,html,expected_version):
    with pool.connection() as c:
        c.execute("SELECT invoice_id FROM audit.invoice_audit WHERE invoice_id=%s FOR UPDATE",(invoice_id,))
        version = c.execute("SELECT COALESCE(MAX(version),0) AS v FROM audit.audit_runs WHERE invoice_id=%s",(invoice_id,)).fetchone()["v"]
        if version != expected_version: raise ValueError("Concurrent report change; retry")
        version += 1
        report["version"] = version
        run = c.execute("""INSERT INTO audit.audit_runs(invoice_id,version,effective_input,report,html)
            VALUES (%s,%s,%s,%s,%s) RETURNING id""",(invoice_id,version,Jsonb(invoice.model_dump(mode="json")),Jsonb(report),html)).fetchone()["id"]
        for f in report["findings"]:
            c.execute("""INSERT INTO audit.discrepancies(run_id,invoice_id,field_name,invoice_value,erp_value,deviation_pct,severity,rule_id,line_number)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(run,invoice_id,f["field"],f["actual"],f["expected"],f["deviation_percent"],f["severity"],f["rule_id"],f["line_number"]))
        c.execute("""INSERT INTO audit.rag_index_status(invoice_id,version,status) VALUES (%s,%s,'pending')
            ON CONFLICT(invoice_id) DO UPDATE SET version=excluded.version,status='pending',error=NULL""",(invoice_id,version))
        c.execute("UPDATE audit.human_feedback SET revalidated=true WHERE invoice_id=%s",(invoice_id,))
        c.execute("UPDATE audit.invoice_audit SET status='completed',error=NULL WHERE invoice_id=%s",(invoice_id,))
    return version

def index_status(invoice_id,version,status,error=None):
    with pool.connection() as c:
        c.execute("""INSERT INTO audit.rag_index_status VALUES (%s,%s,%s,%s)
            ON CONFLICT(invoice_id) DO UPDATE SET version=excluded.version,status=excluded.status,error=excluded.error""",(invoice_id,version,status,error))

from contextlib import contextmanager
@contextmanager
def claim(invoice_id):
    """Session advisory lock prevents concurrent work on one invoice across processes."""
    with pool.connection() as c:
        acquired=c.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok",(invoice_id,)).fetchone()["ok"]
        if not acquired: raise ValueError("Invoice is already being processed")
        try: yield
        finally: c.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))",(invoice_id,))

"""Small, durable SQLite repository for laptop work; money stays decimal text."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from agent.models import Invoice
from agent.corrections import apply_feedback,prepare_correction
from agent.settings import ROOT

class Store:
    def __init__(self,path=None):
        self.path=Path(path or ROOT/".local/laptop.db")
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY, checksum TEXT UNIQUE, path TEXT,
                status TEXT NOT NULL DEFAULT 'detected', raw TEXT, method TEXT, translation TEXT, original TEXT, error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS lines(invoice_id TEXT, number INTEGER, item_code TEXT, quantity TEXT,
                unit_price TEXT,line_total TEXT,description TEXT,PRIMARY KEY(invoice_id,number));
            CREATE TABLE IF NOT EXISTS runs(invoice_id TEXT,version INTEGER,input TEXT,report TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(invoice_id,version));
            CREATE TABLE IF NOT EXISTS feedback(id INTEGER PRIMARY KEY AUTOINCREMENT,invoice_id TEXT,
                field_name TEXT,line_number INTEGER,original_value TEXT,corrected_value TEXT,reviewer TEXT,reason TEXT,
                revalidated INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY,invoice_id TEXT,version INTEGER,
                source_type TEXT,text TEXT,vector TEXT);
            CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,value TEXT,expires REAL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,invoice_id TEXT,path TEXT,duplicate INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS stages(invoice_id TEXT,node TEXT,state TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(invoice_id,node));
            """)
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c; c.commit()
        except Exception:
            c.rollback(); raise
        finally: c.close()
    def detect(self,path,checksum):
        with self.connect() as c:
            row=c.execute("SELECT id FROM invoices WHERE checksum=?",(checksum,)).fetchone()
            fresh=row is None
            invoice_id=str(uuid4()) if fresh else row["id"]
            if fresh: c.execute("INSERT INTO invoices(id,checksum,path) VALUES (?,?,?)",(invoice_id,checksum,str(path)))
            c.execute("INSERT INTO events(invoice_id,path,duplicate) VALUES (?,?,?)",(invoice_id,str(path),int(not fresh)))
        return invoice_id,fresh
    def list(self):
        with self.connect() as c:
            rows=[dict(r) for r in c.execute("SELECT id,status,error,original,created_at FROM invoices ORDER BY created_at DESC,rowid DESC")]
        for row in rows: row["invoice"]=json.loads(row.pop("original") or "null")
        return rows
    def get(self,invoice_id):
        with self.connect() as c:
            r=c.execute("SELECT * FROM invoices WHERE id=?",(invoice_id,)).fetchone()
            if r is None: raise KeyError("Invoice not found")
            row=dict(r)
            row["original"]=json.loads(row["original"] or "null")
            row["translation"]=json.loads(row["translation"] or "null")
            row["runs"]=[{**dict(r),"input":json.loads(r["input"]),"report":json.loads(r["report"])} for r in c.execute("SELECT * FROM runs WHERE invoice_id=? ORDER BY version",(invoice_id,))]
            row["feedback"]=[dict(r) for r in c.execute("SELECT * FROM feedback WHERE invoice_id=? ORDER BY id",(invoice_id,))]
            row["stages"]=[r["node"] for r in c.execute("SELECT node FROM stages WHERE invoice_id=? ORDER BY rowid",(invoice_id,))]
            return row
    def status(self,invoice_id,status,error=None):
        with self.connect() as c: c.execute("UPDATE invoices SET status=?,error=? WHERE id=?",(status,error,invoice_id))
    def save_raw(self,invoice_id,text,method):
        with self.connect() as c: c.execute("UPDATE invoices SET raw=COALESCE(raw,?),method=COALESCE(method,?) WHERE id=?",(text,method,invoice_id))
    def save_extraction(self,invoice_id,invoice,translation):
        with self.connect() as c:
            row=c.execute("SELECT original FROM invoices WHERE id=?",(invoice_id,)).fetchone()
            if row["original"]: return Invoice.model_validate_json(row["original"])
            data=invoice.model_dump_json()
            c.execute("UPDATE invoices SET original=?,translation=? WHERE id=?",(data,json.dumps(translation),invoice_id))
            for line in invoice.line_items:
                c.execute("INSERT INTO lines VALUES (?,?,?,?,?,?,?)",(invoice_id,line.line_number,line.item_code,str(line.quantity) if line.quantity is not None else None,str(line.unit_price) if line.unit_price is not None else None,str(line.line_total) if line.line_total is not None else None,line.description))
        return invoice
    def effective(self,row):
        return apply_feedback(row["original"],row["feedback"])
    def correct(self,invoice_id,correction):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row=self.get(invoice_id)
            if not row["runs"] or row["runs"][-1]["version"]!=correction.expected_version:
                raise ValueError("Report changed; refresh before correcting")
            if any(not x["revalidated"] for x in row["feedback"]): raise ValueError("Revalidate pending correction first")
            original,corrected=prepare_correction(self.effective(row),correction)
            c.execute("INSERT INTO feedback(invoice_id,field_name,line_number,original_value,corrected_value,reviewer,reason) VALUES (?,?,?,?,?,?,?)",
                (invoice_id,correction.field,correction.line_number,original,corrected,correction.reviewer,correction.reason))
    def save_report(self,invoice_id,invoice,report,expected_version):
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            version=c.execute("SELECT COALESCE(MAX(version),0) FROM runs WHERE invoice_id=?",(invoice_id,)).fetchone()[0]
            if version!=expected_version: raise ValueError("Report changed; refresh before revalidating")
            report["version"]=version+1
            c.execute("INSERT INTO runs(invoice_id,version,input,report) VALUES (?,?,?,?)",(invoice_id,version+1,invoice.model_dump_json(),json.dumps(report)))
            c.execute("UPDATE feedback SET revalidated=1 WHERE invoice_id=?",(invoice_id,))
            c.execute("DELETE FROM chunks WHERE invoice_id=?",(invoice_id,))
            c.execute("UPDATE invoices SET status='completed',error=NULL WHERE id=?",(invoice_id,))
    def stage(self,invoice_id,node,state):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO stages(invoice_id,node,state) VALUES (?,?,?)",(invoice_id,node,json.dumps(state)))
    def cached_stage(self,invoice_id,node):
        with self.connect() as c:
            r=c.execute("SELECT state FROM stages WHERE invoice_id=? AND node=?",(invoice_id,node)).fetchone()
        return json.loads(r[0]) if r else None
    def get_meta(self,key):
        with self.connect() as c:
            row=c.execute("SELECT value FROM app_meta WHERE key=?",(key,)).fetchone()
        return row[0] if row else None
    def set_meta(self,key,value):
        with self.connect() as c:c.execute("INSERT OR REPLACE INTO app_meta VALUES (?,?)",(key,value))
    def get_cache(self,key):
        import time
        with self.connect() as c:
            row=c.execute("SELECT value FROM cache WHERE key=? AND expires>?",(key,time.time())).fetchone()
        return row[0] if row else None
    def set_cache(self,key,value,ttl):
        import time
        with self.connect() as c: c.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",(key,value,time.time()+ttl))

class Cache:
    def __init__(self,store): self.store=store
    def get(self,key): return self.store.get_cache(key)
    def setex(self,key,ttl,value): self.store.set_cache(key,value,ttl)

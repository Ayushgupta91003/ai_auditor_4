"""
Audit Database Interface
Provides persistence for invoice audits, line items, discrepancies, and human feedback.
Interacts with PostgreSQL schema 'audit', with automatic SQLite/JSON fallback for local testing.
"""

import os
import json
import uuid
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger("agent_db")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://auditor:auditor_secret@postgres:5432/invoice_db")
BASE_DIR = Path(__file__).resolve().parents[3]
LOCAL_DB_FILE = BASE_DIR / "data" / "local_audit.sqlite"

class AuditDatabase:
    def __init__(self):
        self.use_postgres = False
        self.pool = None
        self._init_connection()

    def _init_connection(self):
        try:
            import psycopg2
            from psycopg2 import pool
            
            # Test connection
            conn = psycopg2.connect(DATABASE_URL, connect_timeout=3)
            # Ensure tables exist
            with conn.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS audit;")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS audit.invoice_audit (
                        invoice_id              UUID PRIMARY KEY,
                        file_path               VARCHAR(512),
                        file_checksum           VARCHAR(64) UNIQUE,
                        extraction_method       VARCHAR(32),
                        raw_extracted_text      TEXT,
                        translated_text         TEXT,
                        source_language         VARCHAR(8),
                        translation_confidence  NUMERIC(4,3),
                        invoice_number          VARCHAR(64),
                        vendor_name             VARCHAR(255),
                        vendor_id               VARCHAR(64),
                        po_number               VARCHAR(64),
                        invoice_date            DATE,
                        currency                CHAR(3),
                        total_amount            NUMERIC(14,2),
                        validation_status       VARCHAR(32),
                        recommendation          VARCHAR(32),
                        risk_score              NUMERIC(6,3),
                        review_status           VARCHAR(32),
                        reviewed_by             VARCHAR(128),
                        reviewed_at             TIMESTAMPTZ,
                        review_notes            TEXT,
                        extracted_raw           JSONB,
                        thread_id               VARCHAR(128),
                        processed_at            TIMESTAMPTZ DEFAULT now()
                    );
                    CREATE TABLE IF NOT EXISTS audit.invoice_line_items (
                        id                      BIGSERIAL PRIMARY KEY,
                        invoice_id              UUID REFERENCES audit.invoice_audit(invoice_id) ON DELETE CASCADE,
                        line_number             INTEGER,
                        item_code               VARCHAR(64),
                        description             TEXT,
                        quantity                NUMERIC(12,3),
                        unit_price              NUMERIC(14,4),
                        line_total              NUMERIC(14,2)
                    );
                    CREATE TABLE IF NOT EXISTS audit.discrepancies (
                        id                      BIGSERIAL PRIMARY KEY,
                        invoice_id              UUID REFERENCES audit.invoice_audit(invoice_id) ON DELETE CASCADE,
                        field_name              VARCHAR(64),
                        invoice_value           TEXT,
                        erp_value               TEXT,
                        deviation_pct           NUMERIC(8,4),
                        severity                VARCHAR(16),
                        detected_at             TIMESTAMPTZ DEFAULT now()
                    );
                    CREATE TABLE IF NOT EXISTS audit.human_feedback (
                        id                      BIGSERIAL PRIMARY KEY,
                        invoice_id              UUID REFERENCES audit.invoice_audit(invoice_id) ON DELETE CASCADE,
                        field_name              VARCHAR(64),
                        original_value          TEXT,
                        corrected_value         TEXT,
                        corrected_by            VARCHAR(128),
                        corrected_at            TIMESTAMPTZ DEFAULT now(),
                        revalidated             BOOLEAN DEFAULT FALSE,
                        decision                VARCHAR(16),
                        notes                   TEXT
                    );
                """)
                # Migrations for pre-existing databases.
                cur.execute("""
                    ALTER TABLE audit.invoice_audit ADD COLUMN IF NOT EXISTS risk_score NUMERIC(6,3);
                    ALTER TABLE audit.invoice_audit ADD COLUMN IF NOT EXISTS review_status VARCHAR(32);
                    ALTER TABLE audit.invoice_audit ADD COLUMN IF NOT EXISTS reviewed_by VARCHAR(128);
                    ALTER TABLE audit.invoice_audit ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;
                    ALTER TABLE audit.invoice_audit ADD COLUMN IF NOT EXISTS review_notes TEXT;
                    ALTER TABLE audit.human_feedback ADD COLUMN IF NOT EXISTS decision VARCHAR(16);
                    ALTER TABLE audit.human_feedback ADD COLUMN IF NOT EXISTS notes TEXT;
                """)
                conn.commit()
            conn.close()

            self.pool = pool.SimpleConnectionPool(1, 10, DATABASE_URL)
            self.use_postgres = True
            logger.info("Connected to PostgreSQL audit schema successfully.")
        except Exception as e:
            logger.warning(f"PostgreSQL audit connection unavailable ({e}). Initializing SQLite fallback store.")
            self.use_postgres = False
            self._init_sqlite()

    def _init_sqlite(self):
        import sqlite3
        LOCAL_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(LOCAL_DB_FILE))
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS invoice_audit (
                invoice_id TEXT PRIMARY KEY,
                file_path TEXT,
                file_checksum TEXT UNIQUE,
                extraction_method TEXT,
                raw_extracted_text TEXT,
                translated_text TEXT,
                source_language TEXT,
                translation_confidence REAL,
                invoice_number TEXT,
                vendor_name TEXT,
                vendor_id TEXT,
                po_number TEXT,
                invoice_date TEXT,
                currency TEXT,
                total_amount REAL,
                validation_status TEXT,
                recommendation TEXT,
                risk_score REAL,
                review_status TEXT,
                reviewed_by TEXT,
                reviewed_at TEXT,
                review_notes TEXT,
                extracted_raw TEXT,
                thread_id TEXT,
                processed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS invoice_line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT,
                line_number INTEGER,
                item_code TEXT,
                description TEXT,
                quantity REAL,
                unit_price REAL,
                line_total REAL
            );
            CREATE TABLE IF NOT EXISTS discrepancies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT,
                field_name TEXT,
                invoice_value TEXT,
                erp_value TEXT,
                deviation_pct REAL,
                severity TEXT,
                detected_at TEXT
            );
            CREATE TABLE IF NOT EXISTS human_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id TEXT,
                field_name TEXT,
                original_value TEXT,
                corrected_value TEXT,
                corrected_by TEXT,
                corrected_at TEXT,
                revalidated INTEGER DEFAULT 0,
                decision TEXT,
                notes TEXT
            );
        """)
        # Migrations for pre-existing SQLite stores.
        self._sqlite_add_missing_columns(cur, "invoice_audit", {
            "risk_score": "REAL", "review_status": "TEXT", "reviewed_by": "TEXT",
            "reviewed_at": "TEXT", "review_notes": "TEXT"
        })
        self._sqlite_add_missing_columns(cur, "human_feedback", {
            "decision": "TEXT", "notes": "TEXT"
        })
        conn.commit()
        conn.close()
        logger.info(f"Initialized SQLite fallback store at {LOCAL_DB_FILE}")

    def _sqlite_add_missing_columns(self, cur, table: str, columns: Dict[str, str]):
        """Adds columns to an existing SQLite table when they are not present yet."""
        cur.execute(f"PRAGMA table_info({table});")
        existing = {row[1] for row in cur.fetchall()}
        for name, coltype in columns.items():
            if name not in existing:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {coltype};")

    def is_checksum_audited(self, checksum: str) -> bool:
        if not checksum:
            return False
        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM audit.invoice_audit WHERE file_checksum = %s LIMIT 1;", (checksum,))
                    return cur.fetchone() is not None
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM invoice_audit WHERE file_checksum = ? LIMIT 1;", (checksum,))
            row = cur.fetchone()
            conn.close()
            return row is not None

    def insert_invoice_audit(self, data: Dict[str, Any]) -> str:
        invoice_id = str(data.get("invoice_id") or uuid.uuid4())
        processed_at = datetime.utcnow().isoformat()
        extracted_raw_json = json.dumps(data.get("extracted_raw", {}))

        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO audit.invoice_audit (
                            invoice_id, file_path, file_checksum, extraction_method,
                            raw_extracted_text, translated_text, source_language,
                            translation_confidence, invoice_number, vendor_name, vendor_id,
                            po_number, invoice_date, currency, total_amount,
                            validation_status, recommendation, extracted_raw, thread_id
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (file_checksum) DO UPDATE SET
                            processed_at = now(),
                            file_path = EXCLUDED.file_path,
                            extraction_method = EXCLUDED.extraction_method,
                            raw_extracted_text = EXCLUDED.raw_extracted_text,
                            translated_text = EXCLUDED.translated_text,
                            source_language = EXCLUDED.source_language,
                            translation_confidence = EXCLUDED.translation_confidence,
                            invoice_number = EXCLUDED.invoice_number,
                            vendor_name = EXCLUDED.vendor_name,
                            vendor_id = EXCLUDED.vendor_id,
                            po_number = EXCLUDED.po_number,
                            invoice_date = EXCLUDED.invoice_date,
                            currency = EXCLUDED.currency,
                            total_amount = EXCLUDED.total_amount,
                            validation_status = EXCLUDED.validation_status,
                            recommendation = EXCLUDED.recommendation,
                            extracted_raw = EXCLUDED.extracted_raw,
                            thread_id = EXCLUDED.thread_id;
                    """, (
                        invoice_id, data.get("file_path"), data.get("file_checksum"),
                        data.get("extraction_method"), data.get("raw_extracted_text"),
                        data.get("translated_text"), data.get("source_language"),
                        data.get("translation_confidence"), data.get("invoice_number"),
                        data.get("vendor_name"), data.get("vendor_id"),
                        data.get("po_number"), data.get("invoice_date") or None,
                        data.get("currency"), data.get("total_amount"),
                        data.get("validation_status", "pending"), data.get("recommendation", "review"),
                        extracted_raw_json, data.get("thread_id")
                    ))
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO invoice_audit (
                    invoice_id, file_path, file_checksum, extraction_method,
                    raw_extracted_text, translated_text, source_language,
                    translation_confidence, invoice_number, vendor_name, vendor_id,
                    po_number, invoice_date, currency, total_amount,
                    validation_status, recommendation, extracted_raw, thread_id, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invoice_id, data.get("file_path"), data.get("file_checksum"),
                data.get("extraction_method"), data.get("raw_extracted_text"),
                data.get("translated_text"), data.get("source_language"),
                data.get("translation_confidence"), data.get("invoice_number"),
                data.get("vendor_name"), data.get("vendor_id"),
                data.get("po_number"), str(data.get("invoice_date")) if data.get("invoice_date") else None,
                data.get("currency"), data.get("total_amount"),
                data.get("validation_status", "pending"), data.get("recommendation", "review"),
                extracted_raw_json, data.get("thread_id"), processed_at
            ))
            conn.commit()
            conn.close()

        return invoice_id

    def insert_line_items(self, invoice_id: str, line_items: List[Dict[str, Any]]):
        if not line_items:
            return
        if self.use_postgres and self.pool:
            from psycopg2.extras import execute_batch
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM audit.invoice_line_items WHERE invoice_id = %s;", (invoice_id,))
                    tuples = [
                        (
                            invoice_id, idx + 1, item.get("item_code"),
                            item.get("description"), item.get("quantity", item.get("qty", 0.0)),
                            item.get("unit_price", 0.0), item.get("line_total", item.get("total", 0.0))
                        )
                        for idx, item in enumerate(line_items)
                    ]
                    execute_batch(cur, """
                        INSERT INTO audit.invoice_line_items (
                            invoice_id, line_number, item_code, description, quantity, unit_price, line_total
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """, tuples)
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute("DELETE FROM invoice_line_items WHERE invoice_id = ?;", (invoice_id,))
            tuples = [
                (
                    invoice_id, idx + 1, item.get("item_code"),
                    item.get("description"), item.get("quantity", item.get("qty", 0.0)),
                    item.get("unit_price", 0.0), item.get("line_total", item.get("total", 0.0))
                )
                for idx, item in enumerate(line_items)
            ]
            cur.executemany("""
                INSERT INTO invoice_line_items (
                    invoice_id, line_number, item_code, description, quantity, unit_price, line_total
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, tuples)
            conn.commit()
            conn.close()

    def insert_discrepancies(self, invoice_id: str, discrepancies: List[Dict[str, Any]]):
        if not discrepancies:
            return
        detected_at = datetime.utcnow().isoformat()
        if self.use_postgres and self.pool:
            from psycopg2.extras import execute_batch
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM audit.discrepancies WHERE invoice_id = %s;", (invoice_id,))
                    tuples = [
                        (
                            invoice_id, d.get("field_name"), str(d.get("invoice_value")),
                            str(d.get("erp_value")), d.get("deviation_pct", 0.0),
                            d.get("severity", "WARNING")
                        )
                        for d in discrepancies
                    ]
                    execute_batch(cur, """
                        INSERT INTO audit.discrepancies (
                            invoice_id, field_name, invoice_value, erp_value, deviation_pct, severity
                        ) VALUES (%s, %s, %s, %s, %s, %s);
                    """, tuples)
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute("DELETE FROM discrepancies WHERE invoice_id = ?;", (invoice_id,))
            tuples = [
                (
                    invoice_id, d.get("field_name"), str(d.get("invoice_value")),
                    str(d.get("erp_value")), d.get("deviation_pct", 0.0),
                    d.get("severity", "WARNING"), detected_at
                )
                for d in discrepancies
            ]
            cur.executemany("""
                INSERT INTO discrepancies (
                    invoice_id, field_name, invoice_value, erp_value, deviation_pct, severity, detected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, tuples)
            conn.commit()
            conn.close()

    def insert_human_feedback(self, invoice_id: str, field_name: str, original_value: str, corrected_value: str, corrected_by: str = "Auditor") -> int:
        corrected_at = datetime.utcnow().isoformat()
        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO audit.human_feedback (
                            invoice_id, field_name, original_value, corrected_value, corrected_by, corrected_at
                        ) VALUES (%s, %s, %s, %s, %s, now()) RETURNING id;
                    """, (invoice_id, field_name, original_value, corrected_value, corrected_by))
                    fb_id = cur.fetchone()[0]
                conn.commit()
                return fb_id
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO human_feedback (
                    invoice_id, field_name, original_value, corrected_value, corrected_by, corrected_at
                ) VALUES (?, ?, ?, ?, ?, ?);
            """, (invoice_id, field_name, original_value, corrected_value, corrected_by, corrected_at))
            fb_id = cur.lastrowid
            conn.commit()
            conn.close()
            return fb_id

    def list_invoices(self) -> List[Dict[str, Any]]:
        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT invoice_id, file_path, invoice_number, vendor_name, vendor_id,
                               po_number, invoice_date, currency, total_amount,
                               validation_status, recommendation, risk_score, review_status,
                               reviewed_by, reviewed_at, translation_confidence, processed_at
                        FROM audit.invoice_audit
                        ORDER BY processed_at DESC;
                    """)
                    cols = [c[0] for c in cur.description]
                    return [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("""
                SELECT invoice_id, file_path, invoice_number, vendor_name, vendor_id,
                       po_number, invoice_date, currency, total_amount,
                       validation_status, recommendation, risk_score, review_status,
                       reviewed_by, reviewed_at, translation_confidence, processed_at
                FROM invoice_audit
                ORDER BY processed_at DESC;
            """)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows

    def get_invoice_details(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        invoice = None
        line_items = []
        discrepancies = []
        feedback = []

        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM audit.invoice_audit WHERE invoice_id = %s;", (invoice_id,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    cols = [c[0] for c in cur.description]
                    invoice = dict(zip(cols, row))

                    cur.execute("SELECT * FROM audit.invoice_line_items WHERE invoice_id = %s ORDER BY line_number;", (invoice_id,))
                    l_cols = [c[0] for c in cur.description]
                    line_items = [dict(zip(l_cols, r)) for r in cur.fetchall()]

                    cur.execute("SELECT * FROM audit.discrepancies WHERE invoice_id = %s;", (invoice_id,))
                    d_cols = [c[0] for c in cur.description]
                    discrepancies = [dict(zip(d_cols, r)) for r in cur.fetchall()]

                    cur.execute("SELECT * FROM audit.human_feedback WHERE invoice_id = %s ORDER BY corrected_at DESC;", (invoice_id,))
                    f_cols = [c[0] for c in cur.description]
                    feedback = [dict(zip(f_cols, r)) for r in cur.fetchall()]
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT * FROM invoice_audit WHERE invoice_id = ?;", (invoice_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return None
            invoice = dict(row)

            cur.execute("SELECT * FROM invoice_line_items WHERE invoice_id = ? ORDER BY line_number;", (invoice_id,))
            line_items = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM discrepancies WHERE invoice_id = ?;", (invoice_id,))
            discrepancies = [dict(r) for r in cur.fetchall()]

            cur.execute("SELECT * FROM human_feedback WHERE invoice_id = ? ORDER BY corrected_at DESC;", (invoice_id,))
            feedback = [dict(r) for r in cur.fetchall()]
            conn.close()

        invoice["line_items"] = line_items
        invoice["discrepancies"] = discrepancies
        invoice["feedback"] = feedback
        return invoice

    def update_review_status(self, invoice_id: str, review_status: str, risk_score: Optional[float] = None,
                             reviewed_by: Optional[str] = None, review_notes: Optional[str] = None):
        """Updates the human-review gate fields on an invoice audit row."""
        reviewed_at = datetime.utcnow().isoformat() if reviewed_by else None
        sets = ["review_status = %s"]
        params: List[Any] = [review_status]
        if risk_score is not None:
            sets.append("risk_score = %s")
            params.append(risk_score)
        if reviewed_by is not None:
            sets.append("reviewed_by = %s")
            params.append(reviewed_by)
            sets.append("reviewed_at = now()")
        if review_notes is not None:
            sets.append("review_notes = %s")
            params.append(review_notes)

        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE audit.invoice_audit SET {', '.join(sets)} WHERE invoice_id = %s;",
                        params + [invoice_id]
                    )
                conn.commit()
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            sq_sets = ["review_status = ?"]
            sq_params: List[Any] = [review_status]
            if risk_score is not None:
                sq_sets.append("risk_score = ?")
                sq_params.append(risk_score)
            if reviewed_by is not None:
                sq_sets.append("reviewed_by = ?")
                sq_params.append(reviewed_by)
                sq_sets.append("reviewed_at = ?")
                sq_params.append(reviewed_at)
            if review_notes is not None:
                sq_sets.append("review_notes = ?")
                sq_params.append(review_notes)
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute(
                f"UPDATE invoice_audit SET {', '.join(sq_sets)} WHERE invoice_id = ?;",
                sq_params + [invoice_id]
            )
            conn.commit()
            conn.close()

    def record_review_decision(self, invoice_id: str, decision: str, reviewed_by: str = "Auditor", notes: str = "") -> int:
        """Persists an approve/reject decision into audit.human_feedback."""
        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO audit.human_feedback (
                            invoice_id, field_name, original_value, corrected_value,
                            corrected_by, corrected_at, revalidated, decision, notes
                        ) VALUES (%s, 'REVIEW_DECISION', %s, %s, %s, now(), TRUE, %s, %s) RETURNING id;
                    """, (invoice_id, "pending_review", decision, reviewed_by, decision, notes))
                    fb_id = cur.fetchone()[0]
                conn.commit()
                return fb_id
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            corrected_at = datetime.utcnow().isoformat()
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO human_feedback (
                    invoice_id, field_name, original_value, corrected_value,
                    corrected_by, corrected_at, revalidated, decision, notes
                ) VALUES (?, 'REVIEW_DECISION', ?, ?, ?, ?, 1, ?, ?);
            """, (invoice_id, "pending_review", decision, reviewed_by, corrected_at, decision, notes))
            fb_id = cur.lastrowid
            conn.commit()
            conn.close()
            return fb_id

    def record_correction(self, invoice_id: str, field_name: str, original_value: str,
                          corrected_value: str, corrected_by: str = "Auditor", revalidated: bool = True) -> int:
        """Records a field correction that was applied during revalidation."""
        if self.use_postgres and self.pool:
            conn = self.pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO audit.human_feedback (
                            invoice_id, field_name, original_value, corrected_value,
                            corrected_by, corrected_at, revalidated
                        ) VALUES (%s, %s, %s, %s, %s, now(), %s) RETURNING id;
                    """, (invoice_id, field_name, original_value, corrected_value, corrected_by, revalidated))
                    fb_id = cur.fetchone()[0]
                conn.commit()
                return fb_id
            finally:
                self.pool.putconn(conn)
        else:
            import sqlite3
            corrected_at = datetime.utcnow().isoformat()
            conn = sqlite3.connect(str(LOCAL_DB_FILE))
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO human_feedback (
                    invoice_id, field_name, original_value, corrected_value,
                    corrected_by, corrected_at, revalidated
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (invoice_id, field_name, original_value, corrected_value, corrected_by, corrected_at, 1 if revalidated else 0))
            fb_id = cur.lastrowid
            conn.commit()
            conn.close()
            return fb_id

audit_db = AuditDatabase()

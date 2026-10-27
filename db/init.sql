CREATE SCHEMA IF NOT EXISTS erp;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS langgraph;
CREATE TABLE erp.vendors (vendor_id text PRIMARY KEY, name text NOT NULL);
CREATE TABLE erp.sku_master (item_code text PRIMARY KEY, description text NOT NULL);
CREATE TABLE erp.purchase_orders (po_number text PRIMARY KEY, vendor_id text REFERENCES erp.vendors, currency char(3));
CREATE TABLE erp.po_line_items (po_number text REFERENCES erp.purchase_orders, item_code text REFERENCES erp.sku_master, quantity numeric(12,3), unit_price numeric(14,4), PRIMARY KEY(po_number,item_code));
INSERT INTO erp.vendors VALUES ('V001','Global Logistics Supplies');
INSERT INTO erp.sku_master VALUES ('BOX-01','Shipping boxes'),('PAL-01','Wooden pallets');
INSERT INTO erp.purchase_orders VALUES ('PO-1001','V001','EUR');
INSERT INTO erp.po_line_items VALUES ('PO-1001','BOX-01',10,100),('PO-1001','PAL-01',2,50);
CREATE TABLE audit.invoice_audit (
 invoice_id uuid PRIMARY KEY, file_path text NOT NULL, file_checksum char(64) UNIQUE NOT NULL,
 extraction_method text, raw_extracted_text text, translated_text text, source_language text,
 translation_confidence numeric(4,3), invoice_number text, invoice_date date, vendor_name text,
 vendor_id text, po_number text, currency char(3), total_amount numeric(14,2),
 extracted_raw jsonb, status text NOT NULL DEFAULT 'detected', error text,
 thread_id text, processed_at timestamptz DEFAULT now()
);
CREATE TABLE audit.invoice_line_items (
 id bigserial PRIMARY KEY, invoice_id uuid REFERENCES audit.invoice_audit, line_number integer,
 item_code text, description text, quantity numeric(12,3), unit_price numeric(14,4), line_total numeric(14,2),
 UNIQUE(invoice_id,line_number)
);
CREATE TABLE audit.audit_runs (
 id bigserial PRIMARY KEY, invoice_id uuid REFERENCES audit.invoice_audit, version integer NOT NULL,
 effective_input jsonb NOT NULL, report jsonb NOT NULL, html text NOT NULL,
 created_at timestamptz DEFAULT now(), UNIQUE(invoice_id,version)
);
CREATE TABLE audit.discrepancies (
 id bigserial PRIMARY KEY, run_id bigint REFERENCES audit.audit_runs, invoice_id uuid REFERENCES audit.invoice_audit,
 field_name text, invoice_value text, erp_value text, deviation_pct numeric(12,4), severity text, rule_id text, line_number integer
);
CREATE TABLE audit.human_feedback (
 id bigserial PRIMARY KEY, invoice_id uuid REFERENCES audit.invoice_audit, field_name text NOT NULL,
 line_number integer, original_value text, corrected_value text, corrected_by text NOT NULL, reason text NOT NULL,
 corrected_at timestamptz DEFAULT now(), revalidated boolean NOT NULL DEFAULT false
);
CREATE TABLE audit.rag_index_status (
 invoice_id uuid PRIMARY KEY REFERENCES audit.invoice_audit, version integer, status text, error text
);
CREATE INDEX ON audit.invoice_audit(vendor_id,processed_at);
CREATE INDEX ON audit.audit_runs(invoice_id,version DESC);

CREATE TABLE audit.file_events (
 id bigserial PRIMARY KEY, invoice_id uuid REFERENCES audit.invoice_audit, file_path text NOT NULL,
 file_checksum char(64) NOT NULL, duplicate boolean NOT NULL, detected_at timestamptz DEFAULT now()
);

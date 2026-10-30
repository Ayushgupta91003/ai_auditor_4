-- ==============================================================================
-- AI Invoice Auditor – Database Initialization Script (PostgreSQL 16)
-- Creates schemas: erp, audit, langgraph
-- ==============================================================================

-- Create extension for UUID generation if needed
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------------------------
-- 1. SCHEMAS
-- ------------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS erp;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS langgraph;

-- ------------------------------------------------------------------------------
-- 2. ERP MASTER SCHEMA (Owned & queried strictly by mock-erp service)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS erp.vendors (
    vendor_id       VARCHAR(64) PRIMARY KEY,
    vendor_name     VARCHAR(255) NOT NULL,
    country         VARCHAR(64),
    currency        VARCHAR(10) NOT NULL
);

CREATE TABLE IF NOT EXISTS erp.sku_master (
    item_code       VARCHAR(64) PRIMARY KEY,
    category        VARCHAR(64),
    uom             VARCHAR(32),
    gst_rate        NUMERIC(5,2) DEFAULT 0
);

CREATE TABLE IF NOT EXISTS erp.purchase_orders (
    po_number       VARCHAR(64) PRIMARY KEY,
    vendor_id       VARCHAR(64) REFERENCES erp.vendors(vendor_id),
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS erp.po_line_items (
    id              BIGSERIAL PRIMARY KEY,
    po_number       VARCHAR(64) REFERENCES erp.purchase_orders(po_number) ON DELETE CASCADE,
    item_code       VARCHAR(64) REFERENCES erp.sku_master(item_code),
    description     TEXT,
    qty             NUMERIC(12,3) NOT NULL,
    unit_price      NUMERIC(14,4) NOT NULL,
    currency        VARCHAR(10) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_po_line_items_po ON erp.po_line_items(po_number);

-- ------------------------------------------------------------------------------
-- 3. AUDIT SCHEMA (Owned by agent service, read by streamlit-ui)
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.invoice_audit (
    invoice_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
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
    validation_status       VARCHAR(32),         -- passed | failed | partial
    recommendation          VARCHAR(32),         -- approve | review | reject
    risk_score              NUMERIC(6,3),        -- weighted discrepancy risk score
    review_status           VARCHAR(32),         -- auto_approved | pending_review | approved | rejected
    reviewed_by             VARCHAR(128),
    reviewed_at             TIMESTAMPTZ,
    review_notes            TEXT,
    extracted_raw           JSONB,               -- variable leftovers
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
    decision                VARCHAR(16),          -- approved | rejected (for REVIEW_DECISION rows)
    notes                   TEXT
);

CREATE INDEX IF NOT EXISTS idx_invoice_audit_checksum ON audit.invoice_audit(file_checksum);
CREATE INDEX IF NOT EXISTS idx_invoice_audit_po ON audit.invoice_audit(po_number);
CREATE INDEX IF NOT EXISTS idx_invoice_line_items_inv ON audit.invoice_line_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_discrepancies_inv ON audit.discrepancies(invoice_id);
CREATE INDEX IF NOT EXISTS idx_feedback_inv ON audit.human_feedback(invoice_id);

-- ------------------------------------------------------------------------------
-- 4. ERP MASTER DATA SEED (loads automatically on first container start)
--    Satisfies the single-command startup requirement: no manual seed step.
--    Source of truth: data/ERP_mockdata/*.json
-- ------------------------------------------------------------------------------
INSERT INTO erp.vendors (vendor_id, vendor_name, country, currency) VALUES
    ('VEND-001', 'Global Logistics Ltd',    'UK',      'USD'),
    ('VEND-002', 'BlueOcean Transport Co.', 'USA',     'USD'),
    ('VEND-003', 'Transporte Ibérico S.A.', 'Spain',   'EUR'),
    ('VEND-004', 'HafenLogistik GmbH',      'Germany', 'EUR'),
    ('VEND-005', 'SwiftMove Couriers',      'USA',     'USD'),
    ('VEND-006', 'OceanFreight Pvt Ltd',    'India',   'INR')
ON CONFLICT (vendor_id) DO NOTHING;

INSERT INTO erp.sku_master (item_code, category, uom, gst_rate) VALUES
    ('SKU-001', 'Packaging', 'roll',    10),
    ('SKU-002', 'Safety',    'pair',    10),
    ('SKU-003', 'Safety',    'piece',   10),
    ('SKU-101', 'Logistics', 'piece',   10),
    ('SKU-201', 'Packaging', 'box',     10),
    ('SKU-202', 'Packaging', 'label',   10),
    ('SKU-301', 'Transport', 'crate',   10),
    ('SKU-302', 'Safety',    'vest',    10),
    ('SKU-401', 'Charges',   'service', 10),
    ('SKU-402', 'Packaging', 'box',     10),
    ('SKU-501', 'Transport', 'service', 10)
ON CONFLICT (item_code) DO NOTHING;

INSERT INTO erp.purchase_orders (po_number, vendor_id) VALUES
    ('PO-1001', 'VEND-001'),
    ('PO-1002', 'VEND-002'),
    ('PO-1003', 'VEND-003'),
    ('PO-1004', 'VEND-004'),
    ('PO-1005', 'VEND-005'),
    ('PO-1006', 'VEND-006')
ON CONFLICT (po_number) DO NOTHING;

INSERT INTO erp.po_line_items (po_number, item_code, description, qty, unit_price, currency) VALUES
    ('PO-1001', 'SKU-001', 'Pallet Wrapping Film',    50,  12.00,   'USD'),
    ('PO-1001', 'SKU-002', 'Industrial Gloves',       120, 3.00,    'USD'),
    ('PO-1001', 'SKU-003', 'Safety Helmets',          30,  15.00,   'USD'),
    ('PO-1002', 'SKU-101', 'Container Seals',         200, 1.25,    'USD'),
    ('PO-1003', 'SKU-201', 'Cajas de carton',         100, 2.50,    'EUR'),
    ('PO-1003', 'SKU-202', 'Etiquetas adhesivas',     300, 0.30,    'EUR'),
    ('PO-1004', 'SKU-301', 'Transportkisten',         40,  25.00,   'EUR'),
    ('PO-1004', 'SKU-302', 'Sicherheitswesten',       60,  10.00,   'EUR'),
    ('PO-1005', 'SKU-401', 'Fuel Surcharge',          1,   120.00,  'USD'),
    ('PO-1005', 'SKU-402', 'Express Delivery Boxes',  25,  4.50,    'USD'),
    ('PO-1006', 'SKU-501', 'Container Transport',     5,   8000.00, 'INR');

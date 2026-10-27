# Agent API reference

Base URL inside Compose: http://agent:8000. Host: http://localhost:8000 or lab-approved port forwarding. All routes except GET /health require `Authorization: Bearer <SERVICE_TOKEN>`. UI adds it internally; do not place the token in a browser URL.

| Method/path | Purpose / body |
|---|---|
| GET /health | PostgreSQL and Redis reachability |
| GET /invoices | Recent audit registrations |
| GET /invoices/{uuid} | Original extraction, feedback and report versions |
| POST /upload | Multipart file: PDF, DOCX or PNG; configured maximum 15 MB |
| GET /invoices/{uuid}/report | Latest escaped HTML report |
| POST /invoices/{uuid}/retry | Explicitly resume a failed/interrupted workflow |
| POST /invoices/{uuid}/corrections | JSON field, value, optional line_number, reviewer, reason, expected_version |
| POST /invoices/{uuid}/revalidate | Retry pending saved feedback |
| POST /questions | JSON question and optional invoice_id |
| POST /index/rebuild | Rebuild derived evidence for completed invoices |
| GET /reporting/.well-known/agent-card.json | Authenticated A2A discovery |
| POST /reporting/ | A2A JSON-RPC message/send through SDK |

Correction example: {"field":"invoice_number","value":"INV-ENGLISH-001-CORRECTED","reviewer":"Member 4","reason":"Review demonstration","expected_version":1}. Header fields omit line_number; UI line 0 is translated to null. A numeric line correction must include a positive line number.

ERP service: host port 8001, internal mock-erp:8000. It provides the approved vendor/SKU/PO data through bounded HTTP APIs. Agent never queries erp tables directly. See mock_erp/main.py for exact endpoints. Streamlit uses database read-only transactions for review; all business writes go through the agent API.

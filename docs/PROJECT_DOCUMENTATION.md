# AI Invoice Auditor: project documentation

## Purpose and boundaries

The system extracts multilingual invoices, translates evidence, compares structured values with approved ERP purchase orders, records discrepancies and produces recommendations for human review. It also supports questions grounded in saved evidence and reviewer corrections with retained history. It does not execute payments. Synthetic fixtures are explicitly labelled. Final runtime is AWS Bedrock; Groq is a separate temporary developer profile.

## Architecture

Six services run on one Compose network. Streamlit calls the authenticated agent API and reads audit SQL in read-only transactions. The FastAPI agent orchestrates LangGraph, invokes stdio MCP tools and delegates business explanation to Google ADK reporting through an A2A HTTP adapter. Only mock-erp reads the ERP schema; agent ERP lookups use HTTP. PostgreSQL owns original extracted data, typed rows, feedback, report versions and checkpoints. Qdrant stores derived evidence vectors; Redis stores expiring recomputable caches. External dependencies are AWS Bedrock and configured Langfuse.

See HLD_ARCHITECTURE.png, ARCHITECTURE_AND_TEAM_PLAN.md and README.md. Local laptop mode at port 8765 replaces the final storage/provider with SQLite, lexical vectors and temporary Groq. It is useful for development and does not prove that the final distributed integrations ran.

## Invoice workflow

1. Upload or watched folder supplies a complete file; upload uses a pending name and atomic rename.
2. SHA-256 checksum prevents duplicate registrations. File events preserve detections.
3. Direct text extraction is preferred for digital PDF/DOCX; image/scanned documents use OCR. The agent image includes Tesseract English/Spanish/German and Poppler.
4. Translation returns a validated language, translated text and bounded self-assessed confidence. Raw and translated text remain durable. Confidence is not a calibrated probability.
5. Model output is parsed into Pydantic Invoice/LineItem contracts with Decimal fields. Invalid structured outputs are retried within defined bounds, not silently accepted.
6. YAML rules check required fields, line arithmetic, totals/tax and ERP line prices/quantities. ERP matching is obtained from mock-erp HTTP endpoints.
7. Deterministic findings establish recommendation; generated prose explains these facts. Currency checking rejects explanations introducing unsupported currency symbols/codes and uses a deterministic explanation instead.
8. Persist immutable report versions and effective input snapshots; build escaped HTML and JSON. Index canonical invoice/report facts in Qdrant, not generated explanation prose.
9. LangGraph checkpoints allow explicit resume after a failure. A failed optional export must not undo a committed audit report.

## Data model

| Schema/table | Responsibility |
|---|---|
| erp.vendors / sku_master / purchase_orders / po_line_items | Synthetic approved reference data |
| audit.invoice_audit | Checksum, source path, raw/translated evidence, typed headers, original JSON, status |
| audit.invoice_line_items | Original extracted numeric line rows |
| audit.audit_runs | Append-only versions, effective input, JSON report and HTML |
| audit.discrepancies | Computed rules, actual/expected values, deviation and severity |
| audit.human_feedback | Who changed what, reason, timestamp, revalidated status |
| audit.rag_index_status | Report revision and derived index availability |
| audit.file_events | File detections and duplicates |
| langgraph | Durable framework checkpoint tables |

Original extraction is never overwritten by human feedback. Corrections are validated against a known report version, recorded, applied to an effective copy and revalidated. Concurrent stale versions are rejected. Pending feedback survives failures and can be revalidated. Changing a quantity does not infer permission to rewrite dependent totals; validation exposes inconsistencies.

## RAG and SQL

The five RAG roles cover retrieval, reranking, generation, reflection and orchestration. Qdrant evidence is scoped to the selected invoice and current report revision; Bedrock Titan V2 supplies 1024-dimensional embeddings. Latest effective values supersede original extraction after accepted corrections. Canonical report indexing excludes generated prose so an old explanation error cannot become evidence.

Fixed structured question intents use parameterized SQL rather than model-generated unrestricted SQL. Semantic questions retrieve evidence, rerank, answer with evidence identifiers and evaluate answer relevance, context relevance and groundedness. The average must be strictly greater than 0.7. One initial attempt plus at most three retries is allowed; insufficient evidence leads to abstention. Scores are model estimates. Redis keys include scope/report revision so corrections do not reuse an earlier answer. Derived vectors can be rebuilt from PostgreSQL without OCR or original file reads.

## MCP, ADK and A2A

MCP is the Model Context Protocol tool boundary: the client initializes a real stdio SDK session, discovers tools and calls the named tools with validated payloads. It is not exposed as an unauthenticated public server. Google ADK defines the reporting agent; the A2A SDK adapter exposes agent-card discovery and message/send. The workflow invokes this boundary rather than calling an ADK method directly in the final profile. A2A task storage itself is ephemeral; business reports and workflow checkpoints are durable in PostgreSQL.

## LLM initialization

agent/llm.py creates ChatBedrockConverse lazily and registers it as an in-process LiteLLM custom provider. This keeps a single chat gateway and uses the AWS SDK credential chain. Models, region and optional guardrail identifiers are runtime settings. Translation, structured parsing, reporting and RAG use the gateway. Bedrock embeddings use InvokeModel because Converse is for chat. No OpenAI/Gemini provider is initialized by the application. Some SDKs have transitive provider packages; that does not mean their services are called.

## Security and operations

Runtime service bearer tokens protect the agent and A2A routes; this is lab service authentication, not employee SSO. Private env files, virtual environments, audit stores and uploads are excluded from Git. Containers run without root by default; Linux lab UID/GID can match the user for bind mounts. HTML is escaped. ERP/SQL contracts are bounded. Trace observations contain operation names/status, not invoice text, prompts or keys. Do not log or publish compose config output with expanded secrets.

PostgreSQL/Qdrant named volumes survive normal down/up. Redis deliberately has no volume. Every schema bootstrap on a genuinely fresh database seeds only synthetic ERP reference rows. Never erase working volumes to demonstrate reset; the dedicated isolated verification script creates its own disposable project. Current single-agent watcher is intended for a teaching lab; multi-worker deployment requires shared document storage and a durable queue. TLS/user authentication and least-privilege distinct DB roles are production extensions.

## Verification and limitations

See VERIFICATION.md and REQUIREMENTS_MATRIX.md. Automated tests include real SDK transports with synthetic/stubbed model responses; this is different from live Bedrock output accuracy. Existing user screenshots demonstrate English/Spanish/German local Groq cases. Docker health, image checks and isolated persistence were verified. Langfuse smoke trace export/read-back was verified. Lab Bedrock entitlement, lab networking and original external dataset remain external acceptance checks. The active default model adjustment is disclosed in MODEL_COMPATIBILITY.md.

## Repository guide

START_HERE_NUVEPRO.md is the first-run guide. TEAM_MEMBER_GUIDE.md gives four substantive ownership areas and viva notes. ACCEPTANCE_CHECKLIST.md records tomorrow's lab results. API_REFERENCE.md documents service endpoints. presentation/ contains a five-slide handoff presentation. Do not claim assigned ownership is a historical record of who wrote each line; team members should review, test and personalize their parts before presenting.

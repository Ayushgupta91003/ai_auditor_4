# AI Invoice Auditor

**Current laptop/Groq setup:** see [LOCAL_QUICKSTART](docs/LOCAL_QUICKSTART.md). Run `START_LOCAL.cmd`, open `http://127.0.0.1:8765`, then enter your key in **Groq setup**. This temporary profile needs neither AWS nor Docker. The six-service Bedrock profile below is preserved for the final lab.


A simple Python implementation of the supplied capstone, including the six-service containerized extension. **Source is implemented; live AWS and container integration are not yet verified on this Windows machine.** See `docs/BUILD_STATUS.md` for exact evidence and remaining checks.

## Start in the NuvePro lab

Prerequisites: Docker Engine + Compose v2, internet for image/package downloads, AWS Bedrock credentials with model access, and a LangFuse endpoint for tracing. This project does not require Windows administrator permission to edit or inspect the code.

1. Copy `.env.example` to `.env`. Set a private database password, matching `DATABASE_URL`, a random `SERVICE_TOKEN`, AWS credentials/region, and accessible Bedrock model IDs. Supply temporary `AWS_SESSION_TOKEN` when appropriate. Configure LangFuse keys/host. Never commit `.env` or paste credentials into reports.
2. In this directory run:

```sh
docker compose up --build -d
docker compose ps
```

3. Open [the dashboard](http://localhost:8501). Upload `samples/english.pdf`, then `samples/spanish.docx`, then `samples/german.png`. Alternatively copy a sample to `data/incoming`. Samples are intentionally not auto-ingested at startup, so an empty audit database remains demonstrably empty after a reset.
4. English should match PO-1001. Spanish contains a 20% price mismatch. German contains a 20% quantity mismatch. Review the line findings, download HTML/JSON, correct a field, inspect the new report version, and ask “Why was this invoice flagged?”. Model extraction/OCR quality must be verified against these expected facts.

Model access is account- and region-dependent. Bedrock defaults use Nova Lite for chat/translation/RAG and Titan V2 embeddings. The brief names Command R+, but AWS retired that model on 2026-08-19; see docs/MODEL_COMPATIBILITY.md. Override IDs or inference profile IDs at runtime if required by your lab; do not silently substitute another provider. In the Bedrock profile, all chat models initialize in `agent/llm.py` using **ChatBedrockConverse**. A registered LiteLLM custom provider wraps that client to preserve the in-process gateway requirement. Embeddings use Bedrock InvokeModel because Converse is a chat API. No OpenAI or Gemini client is initialized. The user-authorized Groq laptop profile is documented separately.

## How the code fits together

| File / directory | Purpose |
|---|---|
| `agent/workflow.py` | LangGraph invoice nodes, detection, explicit resume, revalidation |
| `agent/extraction.py`, `translation.py` | Full text extraction, OCR fallback, translation, typed parsing |
| `agent/validation.py` | YAML completeness rules, Decimal math, HTTP-only ERP matching |
| `agent/repository.py`, `db/init.sql` | SQL, original extraction, typed line rows, immutable correction/report history |
| `agent/mcp_server.py`, `mcp_client.py` | Real MCP stdio discovery and tool invocation |
| `agent/reporting.py` | Google ADK BaseAgent, actual A2A SDK adapter, escaped HTML reports |
| `agent/rag.py` | Index/retrieve/rerank/generate/reflect, scoped vectors, bounded retries |
| `agent/llm.py` | Single chat gateway, Redis TTL response cache, Bedrock embeddings |
| `mock_erp/` | FastAPI PO/vendor/SKU service; only this application reads ERP tables |
| `ui/` | Streamlit audit review and append-only corrections |
| `configs/`, `agent/prompts/` | Dynamic rules, personas, prompt templates |
| `docs/TEAM_HANDOFF.md` | Four balanced responsibilities and demo expectations |

## Data and operational behavior

PostgreSQL holds three schemas: `erp`, `audit`, `langgraph`. It stores full raw/translated text, typed headers and line rows, every computed discrepancy, report versions and human feedback. Original file bytes remain in the mounted folder. `extra_fields` preserves format-specific string fields in JSONB. Monetary calculations use Decimal and NUMERIC.

Qdrant holds one derived collection with invoice ID, chunk text, source type, vendor, language and report version. Named volumes preserve PostgreSQL and Qdrant through `docker compose down`. Rebuild Qdrant through `POST /index/rebuild`; no original files or OCR are needed. Redis has no volume and only contains expiring, recomputable values. A report-version change invalidates old answer caches and marks old vectors unavailable until reindexing completes.

A human correction INSERTs feedback. It never overwrites original extracted fields or line rows. Revalidation applies feedback to an effective copy and INSERTs a new report. If revalidation fails, pending feedback remains durable; use “Revalidate pending correction”. Failed/interrupted workflows can resume their LangGraph checkpoints through the dashboard. They are not silently re-extracted on every folder scan.

The six named services and host ports match the brief. Container traffic uses service names, not host ports. `mock-erp` is internally `http://mock-erp:8000`, while its host port is 8001. The dashboard uses read-only SQL transactions; writes go through the agent. This teaching build shares one database credential as described in the brief; separate database roles would strengthen enforcement in production.

A2A reporting is mounted at `/reporting`; discovery is `/reporting/.well-known/agent-card.json`. The adapter targets protocol 0.3 through the pinned A2A SDK. The stateless report task store is ephemeral; business evidence/report history and LangGraph checkpoints remain PostgreSQL-backed. MCP runs as a managed stdio subprocess, discovers tools before calling them, and never exposes an unauthenticated network tool port. API and A2A calls require a runtime bearer service token. This is service authentication, not a full employee SSO system; deploy only in the isolated lab network until user authentication/TLS is added.

LangFuse receives operation names and status only, not invoice text, prompts or credentials. Configure an external instance: adding a self-hosted LangFuse stack would exceed the specified six containers. This resolves the brief's tension between “only Bedrock external” and its LangFuse requirement explicitly. Unconfigured tracing must not be presented as completed observability evidence.

RAG uses five named roles. Reflection checks answer relevance, context relevance and groundedness; an average **strictly greater than 0.7** is required. One initial attempt plus at most three retries is allowed. Unsupported questions abstain. Evidence IDs must be cited. Model scores are quality estimates, not guarantees. Supported structured intents (“How many invoices?”, “What is the invoice total?”) use fixed parameterized SQL. The question cache includes scope and corpus report revision.

## Tests and verification

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m compileall -q agent mock_erp ui scripts tests
python scripts/verify_stack.py
```

`verify_stack.py` is a non-destructive smoke check for a running configured stack. The full six-check procedure, including persistence and an isolated destructive reset, is in `docs/VERIFICATION.md`. Do not run a volume deletion against a database containing work you need.

## Source limitations

The supplied PDF references `Masked Invoice.pdf` and `erp_schema.sql`, but neither separate attachment was provided. All sample invoices and ERP seed data here are team-created synthetic fixtures. They do not replace acceptance testing on the actual dataset. Live mailbox integration is design-only, as permitted: poll unread message IDs via an authorized mail API, save attachments atomically to incoming, store message IDs/checksums, and acknowledge mail only after durable audit registration.

Current design uses one agent process / watcher and serial file ingestion. Database claims protect individual workflow execution, but horizontal multi-worker ingestion would also need shared/object storage and a durable work queue. Scale the UI and read-only ERP API independently; size PostgreSQL/Qdrant deliberately rather than adding replicas blindly.

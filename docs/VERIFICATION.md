# Verification procedure

Record commands, sanitized screenshots and observed results in the lab. Do not claim checks that were only read or authored. Configure `.env` first. Run from this project directory.

## Incremental build

The specification recommends building mock-erp, UI, then agent. Use `docker compose build mock-erp`, then `docker compose build streamlit-ui`, then `docker compose build agent`. Inspect each explicit image tag using `docker image inspect` and `docker history`. The agent's approximate 1.5 GB size goal is not yet measured. OCR packs are eng/spa/deu for the synthetic dataset; adjust after inspecting the actual masked dataset.

Start `postgres qdrant redis` first. Confirm health; then add `mock-erp`, `agent`, `streamlit-ui`. Finally prove a fresh single-command startup using a separate disposable project.

## Required checks

1. **Startup:** `docker compose up --build -d`; all six services become healthy. `python scripts/verify_stack.py` checks HTTP readiness, the ERP seed, service count and host reachability. Never publish output from `docker compose config` or `env` containing real secrets.
2. **End-to-end:** upload English, Spanish and German samples in different formats. Confirm saved raw text, typed invoice and line rows, HTTP ERP comparison, JSON/HTML reports, translation score and a Qdrant-ready status. Query with invoice filter and inspect evidence and triad scores. Repeat the same file under a new name; it must resolve to the same audit ID and record a duplicate file event.
3. **Persistence:** save invoice ID, report version, feedback and cited RAG answer. Keep incoming unchanged. Run `docker compose down`, then `docker compose up -d`. The same audit/report/vector data must remain without reprocessing. Compare row counts and version numbers before/after. Incomplete workflows should be resumable using their checkpoint.
4. **Deliberate data loss, isolated only:** create a separate project/directory and synthetic data. Ensure incoming is empty and set WATCH_ENABLED=false so reingestion cannot hide empty audit state. Run `docker compose down -v` only there, then `docker compose up --build -d`. Confirm audit rows and invoice vectors are empty. ERP fixture rows reappear because initialization intentionally seeds them. Explain that `-v` deleted named volumes. This test destroys data; it is intentionally not automated against the current project.
5. **Secrets:** inspect `docker history invoice-agent:1.0 --no-trunc` and the other two images. No secret values or `.env` contents may appear. The root and Dockerfile-specific ignore files exclude `.env`, VCS and virtualenvs. Runtime env vars are not build args. Do not include real keys in demo evidence.
6. **Discovery:** `docker compose exec agent python -c "import socket; print({n: socket.gethostbyname(n) for n in ['postgres','qdrant','redis','mock-erp']})"`. Addresses must resolve from service names. Run `docker compose exec agent python -m agent.protocol_smoke` to discover all 12 MCP tools and invoke the real ADK reporter through A2A and Bedrock. This uses the configured AWS account. Also inspect the A2A card with a bearer token.

## Recovery and failure cases

- Flush only the disposable Redis cache, repeat translation/question and confirm correct recomputation.
- In an isolated test stack lose only Qdrant data, recreate collection and call `/index/rebuild`. Temporarily withhold original invoice files; raw text and report text in PostgreSQL must suffice.
- Kill/restart the agent during a workflow and resume by invoice ID. Confirm original extraction was not overwritten and report versions do not duplicate.
- Save a human correction, simulate ERP/AWS failure, then use revalidate pending correction. Feedback must survive and original fields must remain unchanged.
- Simulate missing PO, missing SKU, duplicate item codes, absent required field, corrupted PDF, empty scan, unsupported file, unavailable ERP, low translation confidence, unanswerable question and low RAG triad scores.
- Confirm average ==0.7 is rejected and retries stop after one initial attempt plus three retries.
- Observe a configured LangFuse trace without raw invoice text/credentials. No LangFuse configuration means this check is pending.

## Security and scale limits

This is a private-lab teaching build. Service bearer authentication protects agent/A2A endpoints; employee login and TLS are future deployment work. PostgreSQL uses a shared configured credential; UI reads in read-only transactions, not a dedicated least-privilege role. Original files and Redis can contain sensitive content and belong on protected lab storage. If scaling agent workers, add a durable queue and shared storage; keep the serial-watcher limitation explicit.

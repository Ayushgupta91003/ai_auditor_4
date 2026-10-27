# Build status and continuation checkpoint

Date: 2026-10-27. Root: `ai-invoice-auditor` inside the existing workspace.

## Authored

- Updated HLD image and four-member plan.
- Six-service Compose stack and three explicitly versioned, non-root Dockerfiles with dependency-first layers and Dockerfile-specific ignore files.
- LangGraph invoice workflow with PostgreSQL checkpointer, actual MCP client/server, Google ADK BaseAgent exposed through A2A SDK.
- PDF/DOCX/PNG extraction with scanned-PDF OCR fallback; eng/spa/deu OCR packs; automatic language detection, Bedrock translation and typed extraction.
- ChatBedrockConverse-only initialization behind a LiteLLM custom provider; Titan Bedrock embeddings; Redis TTL caches; optional Bedrock guardrail configuration.
- Dynamic field/tolerance rules; Decimal totals/tax; HTTP-only PO/vendor/SKU comparison; detailed findings and JSON/HTML reports.
- PostgreSQL original data/line rows, append-only feedback and report versions, durable raw text, separate index readiness.
- Five-role LangGraph RAG, Qdrant payload filters, reranking, generation, triad reflection and three-retry budget, narrow SQL intent route.
- Streamlit review, corrections, pending-feedback revalidation, evidence view, versioned downloads; redacted LangFuse instrumentation.
- Synthetic English/Spanish/German samples and sample generator; validation tests; operational verification instructions.

## Verified here

- Sixteen validation/correction unit tests pass, including mocked HTTP ERP boundary, Decimal arithmetic, immutable correction inputs and invalid correction rejection.
- Python syntax compilation succeeds across application, scripts and tests.
- Compose YAML parses with exactly six required services. `docker compose config --no-env-resolution --no-interpolate --quiet` passes using a temporary placeholder-only env file, removed immediately afterward.
- HLD image visually inspected. Digital and image-only sample PDFs generated; embedded text / absence of text checked. Sample invoice layout inspected.

## Not yet verified / environmental blockers

- Docker CLI 29.5.3 exists, but the Linux Docker engine pipe is absent. No container was started; no image was built; startup, actual health, OCR, persistence, destructive reset, image size/history and DNS checks remain pending.
- Python dependency installation into project .venv failed because package-index DNS is unavailable. Core tests used the existing bundled Python runtime. Installed-version compatibility, real LangGraph/MCP/ADK/A2A adapter behavior and full integration need execution in the lab.
- No AWS access or model entitlement was verified. No Bedrock call or embedding was made. No LangFuse endpoint was verified. No real credentials were created, copied or requested in chat.
- Missing original Masked Invoice and supplied ERP schema: synthetic replacements are explicitly labeled. Validate actual layouts/language packs when originals become available.
- Final PowerPoint (max five slides) is not authored; its content outline is in TEAM_HANDOFF.md.
- Large-batch throughput, role-based user auth, TLS and multi-worker queue are not production validated.

## Resume without repeating work

1. Read this file, README and VERIFICATION. Retain current code and existing user work.
2. When the lab has network + Docker, configure .env privately and resolve pinned requirements if dependency resolver exposes a conflict. Do not claim integration success based on syntax tests.
3. Build incrementally, execute protocol smoke tests, then the six-service flow. Fix actual failures and record evidence here.
4. Verify synthetic fixtures, corrections and RAG; then restart/rebuild tests on an isolated stack.
5. Test real supplied dataset when available; prepare final five-slide presentation with actual observed evidence.

No Windows elevation was requested. User asked for continuation after interruption; this checkpoint makes work recoverable. Background continuation still depends on an active session or a later resumed session.

## Additional office-session review

Added pure, testable correction helpers and six passing tests. Original extraction is reused when an extraction node is replayed. Reporting checks for an already committed run on replay; optional file-export failure cannot invalidate a report committed to PostgreSQL. Python syntax checks pass. These database/checkpoint recovery paths are authored safeguards and still require the real restart integration test. Docker engine was checked again and remains unavailable. No new permission was requested.

## Current laptop/Groq delivery

User authorized a temporary Groq profile because AWS access is on office laptops only. Added a separate Docker-free laptop application with a native Groq REST adapter, real LangGraph orchestration, durable SQLite originals/line rows/report versions/feedback/stages, local lexical vectors plus model reranking, download/review/correction/QA dashboard, native PDF/DOCX parsing, optional Groq vision fallback for scans, loopback-only binding, private session token, host-header protection, launchers and read-only diagnostics.

**Current verification: 52 tests discovered, 44 passed and 8 skipped.** The 8 HTTP/ASGI tests cannot run here because Windows sandbox loopback sockets are blocked; asyncio's Windows socketpair consequently hangs without the new bounded preflight. Offline end-to-end tests use explicit test-only model responses, real SQLite, LangGraph and mocked HTTP ERP transport. Actual digital PDF/DOCX extraction and scan-routing are tested. No live Groq call was made and no API key was supplied. Browser local-file preview was denied by browser security policy; no visual or live-server verification is claimed.

`docs/LOCAL_QUICKSTART.md` has exact room-time steps and differences between local mode and the final capstone. Local uses direct model explanations/function tools, not ADK/A2A/MCP, and lexical vectors are not Titan semantic embeddings. The original six-service implementations remain pending lab verification. Use `START_LOCAL.cmd` from a normal laptop terminal and privately configure a Groq key for the live local check. No administrator permission was requested.

Final static checks: Python compilation and the dashboard JavaScript syntax check pass. `scripts/test_local.py` writes a machine-readable local test summary without credentials. `scripts/package_project.py` excludes private env files, local databases, uploaded invoices and reports from the handoff archive.

## Evening live acceptance and HTTP verification

The user successfully processed the English sample live through Groq after the missing-language contract fix. Screenshots show INV-ENGLISH-001, approve, 0 findings, EUR 1210, both expected line items, and HTML/JSON downloads. This is user-observed live evidence, separate from mocked automated tests. Spanish, German scan, RAG/corrections and restart acceptance are not yet confirmed.

The offline suite then ran with localhost available: **62 tests passed, zero skipped**, including the eight real ASGI dashboard tests. Model responses remain mocked in automated tests. Report exports now include invoice headers/line items and clean business explanations for new reports. Existing download representations can include the original version's immutable input snapshot without modifying stored history. Full dependency installation and Docker readiness checks are in progress; SDK integration verification remains pending until those finish. No final-completion claim is made.

## Full dependency and protocol verification

Installed the pinned full requirements in the source verification virtual environment, added the local PyMuPDF parser, and ran `pip check`: no broken requirements. The combined suite now reports **66 passed, zero skipped** in that full environment. This includes real MCP SDK initialize/list/call using memory transport and a real PDF harvester, plus real Google ADK/A2A agent-card discovery and message/send execution. Model answers in these automated adapter tests are mocked; this is not a claim of live Groq-through-A2A or a running six-container stack.

Docker Desktop launch was attempted; engine remained unavailable. The user said Docker had not yet been opened manually. LangFuse account/project is not yet created, so no live LangFuse trace has been verified. A credentials-safe CHECK_LANGFUSE.cmd/script and env placeholders are supplied. These dependencies and live acceptance checks remain prerequisites for declaring the final capstone complete.

## Bedrock-first deployment and live LangFuse update

User confirmed Groq is temporary only; final runtime remains LLM_PROVIDER=bedrock and EMBEDDING_PROVIDER=bedrock with ChatBedrockConverse. Added a stubbed actual Converse-through-LiteLLM test, and a future office CHECK_BEDROCK.cmd smoke check for live chat and Titan embeddings. No live Bedrock request has been made.

The user confirmed Spanish price mismatch and a completed German quantity mismatch through screenshots. A separate older German attempt hit Groq rate limits and remains in history. Generated prose had an incorrect dollar symbol on the EUR Spanish invoice; a tested currency guard now falls back to verified findings when prose introduces an unsupported currency.

Docker engine is available. Existing thecoach PostgreSQL uses host port 5432 and was preserved; this project's private .env uses POSTGRES_HOST_PORT=55432 while internal PostgreSQL stays 5432. PostgreSQL/Qdrant/Redis and mock ERP are healthy. ERP initialization loaded one vendor and two PO lines. UI image built; agent image build is in progress.

The user initially placed LangFuse keys in .env.local.example. They were moved privately to .env.local, the example template was reset to blank credentials, and Docker's private .env received the same tracing settings without changing Bedrock/DB settings. Credentials were not printed or included in source packages. Upgraded Langfuse to 4.7.0 and modern observation methods/API for the current server. Live authentication, synthetic observation export and authenticated observation read-back are CONFIRMED. No invoice content was transmitted in smoke traces. Actual app model-call traces require restart under the newly configured environment.

Current full verification suite: **70 passed, zero skipped**, with mocked model responses plus real MCP/A2A and stubbed Bedrock adapters. Actual six-service startup/persistence and live office Bedrock acceptance remain pending.


## Latest verified checkpoint

73 automated tests passed, zero skipped in the full verification environment. Six Docker services are healthy and the live stack smoke check passed. Isolated storage tests passed for retained PostgreSQL audit/history and LangGraph checkpoints, retained Qdrant vectors, disposable Redis cache, and fresh initialization after deleting only test volumes. Live Langfuse smoke trace export and read-back passed. No live Bedrock account/model entitlement test has been performed.

RAG now indexes canonical report facts and effective corrected invoice values, excluding generated explanation prose. Existing local indexes migrate once at startup without new model calls. Final deployment uses ChatBedrockConverse with an active configured model; see MODEL_COMPATIBILITY.md for the retired Command R+ change. Outstanding acceptance: office Bedrock chat/embeddings and permissions, user QA/correction demo, supplied real masked dataset if available, and final presentation.

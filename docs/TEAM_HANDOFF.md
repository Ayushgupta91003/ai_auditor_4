# Four-member implementation and presentation plan

Use member numbers until you add actual names. Each member owns code, unit/integration evidence, documentation and an individual end-to-end demo. Shared interfaces are `Invoice`, `LineItem`, `Finding`, persisted report versions, and the MCP tool schemas. Review changes to these together.

| Member | Main ownership | Files | Demonstration and explanation |
|---|---|---|---|
| 1: Document intelligence | Stable folder detection, checksums, file events, PDF/DOCX/PNG extraction, OCR language packs, translation and structured parsing | `agent/extraction.py`, `translation.py`, monitor portions of `workflow.py`, ingestion MCP tools, extraction/translation prompts, `scripts/make_samples.py` | Process English PDF, Spanish DOCX, German scanned PNG; explain direct-text/OCR routing, language confidence, translation cache and renamed duplicates |
| 2: Audit and enterprise data | PostgreSQL schemas, typed contracts, mock ERP HTTP API, dynamic rules, arithmetic, line matching, discrepancy storage, checkpointer durability | `db/init.sql`, `agent/models.py`, `repository.py`, `validation.py`, `mock_erp/`, `configs/rules.yaml`, validation tests | Show a price/quantity/tax mismatch; trace an ERP HTTP lookup; explain Decimal vs float, typed rows vs JSONB, tolerance policy, audit history vs checkpoints |
| 3: RAG and evidence | Qdrant schema, chunking, Bedrock embeddings, five-role RAG graph, reranking, triad evaluation, bounded retries, SQL routing, version-aware cache, index recovery | `agent/rag.py`, embedding function in `llm.py`, RAG MCP tools, answer/reflection prompts, RAG evaluation fixtures | Ask a scoped question with citations; demonstrate abstention; flush Redis; rebuild Qdrant from PostgreSQL without invoice files or OCR |
| 4: Review and system integration | Streamlit, Google ADK reporting, A2A discovery/invocation, human feedback, HTML/JSON reports, observability, six-service packaging | `ui/`, `agent/reporting.py`, `main.py`, `observability.py`, reporting prompt, Dockerfiles, Compose, verification scripts | Correct an extracted line and show original + new report; demonstrate A2A agent card, redacted trace, container health and retained-volume restart |

## Balanced individual deliverables

Each member prepares: a module walkthrough, a small sequence diagram, at least three meaningful success/failure tests, one fixture with expected output, a 3-minute demo, and two minutes explaining a design trade-off. Member 2 reviews financial invariants; member 3 reviews grounding; member 1 reviews extraction fidelity; member 4 reviews service integration. No member should present only slide design or only deployment commands.

## Integration order

1. Freeze typed Invoice/Finding and report contracts. Seed mock ERP and exercise all three lookup endpoints.
2. Connect extraction and translation to persisted raw text. Confirm scans and failed files remain visible.
3. Connect completeness and business validation; compare the sample outcomes against the fixture truth.
4. Add ADK report explanation over A2A, then HTML/JSON and permanent feedback/revalidation.
5. Index stored invoices/reports; exercise all five RAG roles and the >0.7 retry gate.
6. Verify MCP list/call, LangFuse spans, Compose startup, restart persistence, isolated reset and image history.

## Interface rules

- Member 1 produces an `Invoice` using decimal strings; unknown identifiers remain null.
- Member 2 produces `Finding` rows; severity is `review` or `reject`. Model prose cannot alter findings.
- Member 4's ADK reporter explains an already-computed recommendation. Feedback carries expected report version and reviewer/reason.
- Member 3 indexes the latest report version, ignores stale/unready vectors, and cites `chunk_id`.
- Member 4 owns Compose; each member owns their own dependency and configuration changes. All chat calls go through `llm.py`; never initialize a second provider client.

## Suggested five-slide final presentation

1. Problem, multilingual inputs and a concrete invoice/PO mismatch.
2. Deployed six-service architecture, named volumes and Bedrock Converse gateway.
3. LangGraph invoice flow, ADK/A2A reporting and MCP tool discovery.
4. RAG evidence, human correction history and four-member ownership.
5. Demo evidence: startup, processing, retained restart, isolated reset, secret-safe layers and DNS discovery.

This is presentation content guidance; a final PowerPoint deck is not yet generated.

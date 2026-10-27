# Laptop mode: Groq, no AWS, no Docker

This is the temporary local profile authorized by the user on 2026-10-27. The required Bedrock/six-service capstone profile is retained separately.

## Minimum steps when back at the laptop

1. Double-click `START_LOCAL.cmd` in the project folder. It first tries a usable project virtualenv, then the existing Codex Python runtime, then ordinary Python. No package installation or administrator elevation is requested by this launcher.
2. Open http://127.0.0.1:8765 in your browser.
3. Select **Groq setup**, paste your Groq API key and select a model accessible to your account. The default is `qwen/qwen3.8-27b`, a configurable non-OpenAI/non-Gemini model. **Connect** keeps the key only in the server process; **Check available models** verifies account access by calling Groq's model listing endpoint. It does not print the key.
4. Try **english.pdf** from “Try a synthetic sample”. It should approve against the seeded PO. Then try Spanish DOCX (price discrepancy) and German PNG (quantity discrepancy). Scans use local Tesseract if present, otherwise Groq vision with the configured vision model. The first live model/OCR run still needs verification.

For a key that persists across server restarts, manually copy `.env.local.example` to `.env.local` and fill `GROQ_API_KEY` privately. Do not paste keys into chat. `.env.local` is ignored by Git, Docker build contexts and the source packager. Environment variables already set in the terminal take precedence over the file. If needed change `GROQ_VISION_MODEL` to an accessible vision-capable model.

For another team member's laptop, run `SETUP_LOCAL.cmd` once with Python 3.11+ and internet available; then run `START_LOCAL.cmd`. Each teammate configures their own private Groq key.

If dependencies are missing on another laptop, use a regular Python virtual environment and `python -m pip install -r requirements-local.txt`, then `python run_local.py`. The needed laptop dependencies are already importable through the existing bundled runtime on this machine. `CHECK_LOCAL.cmd` gives a read-only diagnostic report without exposing credentials.

## What the dashboard supports

- PDF, DOCX and PNG uploads; digital PDF text first and scanned-page image transcription fallback.
- Automatic source-language detection/English translation, typed invoice headers/line items, confidence score.
- Shared YAML/Decimal validation rules and PO/vendor/SKU comparisons over the local HTTP ERP routes.
- Recommendations, discrepancy tables, raw/translated text, line items and report version downloads (HTML/JSON).
- Append-only reviewer corrections, pending-feedback recovery, preserved original extraction, versioned reports.
- Scoped questions, evidence IDs, reranking, generated answers and RAG triad quality gate with at most three retries.
- Rebuild search from stored text, duplicate checksums and durable saved workflow stages. Files placed in `.local/incoming` are watched for stable size/mtime before processing.
- Friendly missing-key/rate-limit/model-access failures. A failed invoice remains visible; resume it after fixing configuration rather than repeatedly reuploading it.

## Honest profile differences

| Area | Laptop development | Final lab capstone |
|---|---|---|
| Chat | Groq native REST, configurable Qwen | ChatBedrockConverse through LiteLLM |
| Gateway | Direct local adapter avoids tokenizer downloads | In-process LiteLLM custom provider |
| Orchestration | Real LangGraph with saved successful node outputs | LangGraph with PostgreSQL checkpointer |
| Storage | SQLite, Decimal money stored as text | PostgreSQL NUMERIC, separate audit/ERP/langgraph schemas |
| Search | Download-free lexical vectors plus model reranking | Qdrant + Bedrock Titan semantic embeddings |
| Cache | Expiring, recomputable SQLite cache | Disposable Redis TTL cache |
| Reporting | Shared report formatting + direct model explanation | Google ADK agent invoked through real A2A SDK |
| Tools | Direct local function calls | Actual MCP stdio discovery/invocation |
| ERP | Local HTTP routes with synthetic seed records | Dedicated mock-erp HTTP service reading PostgreSQL |
| UI | Small FastAPI/HTML/JavaScript dashboard | Streamlit container |
| Deployment | One Python process bound to loopback | Six-service Docker Compose stack |

Laptop mode is a useful working development path. It must not be submitted as proof that the PostgreSQL/Qdrant/Redis, MCP, ADK/A2A or six-container requirements passed. Those original implementations remain in `agent/`, `mock_erp/`, `ui/` and `compose.yaml`; they still need lab integration testing.

All local reports, original extracted data, corrections, saved stages and caches are in `.local/laptop.db`. Original uploaded files stay in `.local/incoming`. These private directories are excluded from the source ZIP. Do not delete them if you need your local review history. A cache/index rebuild does not need the original invoice files.

## Verification completed here

- 44 tests passed: financial validation, correction immutability, actual PDF/DOCX text parsing, scan-routing, Groq REST handling with mocked network, real LangGraph workflow, SQLite reopen/persistence, HTTP ERP transport, duplicate checks, model-failure recovery, RAG grounding/citations/retries/cache and scope isolation.
- Model replies are explicitly mocked in offline integration tests. No live Groq or Bedrock call has been made.
- 8 HTTP/ASGI dashboard tests are authored but skipped here because Windows sandbox restrictions block loopback sockets, including the socket pair required by the Python event loop. This also prevents launching the real local web server from this execution environment. The launcher now detects this before it hangs and returns a clear message.
- Browser file preview was rejected by browser security policy. No screenshot or visual acceptance claim is made. No alternate browser workaround was attempted.
- No Windows elevation or network-permission prompt was requested.

## Live checks remaining

Run the launcher in a normal laptop terminal outside the restricted agent execution environment, add a working Groq key and confirm model access. Verify upload, OCR/vision, translation fidelity, report download, correction/revalidation and a cited answer in the browser. Run `python -m unittest discover -s tests -v` there to execute the eight HTTP tests too. Groq account quotas/model entitlements and ordinary local network availability are prerequisites, not something the project can supply.

## Switching back to office/lab Bedrock

Use the main README and `.env.example` with `LLM_PROVIDER=bedrock` and `EMBEDDING_PROVIDER=bedrock`, configure AWS privately and run Compose. This starts the original six-service profile; do not run `run_local.py` for the lab demonstration. The local SQLite database is a development store and is not automatically imported into PostgreSQL. Reprocess the synthetic samples on the lab profile to verify its independent persistence and agent integrations.

## Primary provider references

- Groq model list: https://console.groq.com/docs/models
- Groq quickstart/API key configuration: https://console.groq.com/docs/quickstart
- Groq deprecations: https://console.groq.com/docs/deprecations

Current Groq docs list Qwen 3.8 as a preview model; availability can change. The model ID is editable and the dashboard can list models available to the configured key. The `/openai/v1/` segment is Groq's documented compatibility URL path; the destination is `api.groq.com`, not OpenAI. No OpenAI or Gemini model/provider is selected.

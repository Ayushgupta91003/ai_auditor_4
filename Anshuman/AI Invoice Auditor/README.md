# Current final project: AI Invoice Auditor

This directory contains the selected Anshuman implementation. The original project notes are retained below; their nested-folder links refer to the original export layout. For this repository, run Docker Compose from **this directory**.

```bash
cp .env.example .env
# Configure private database/model/tracing settings for your authorized lab.
docker compose up --build -d
```

Dashboard: http://localhost:8501 on the Docker/lab host. Agent API: port 8000; mock ERP: port 8001. Do not run the old root stack simultaneously on the same ports/image tags. Runtime identity/model availability must be verified in the lab; the code includes deterministic fallback paths.

Read NEW_ADDONS_SPLIT/PROJECT_SIMPLE_OVERVIEW.txt first, then NEW_ADDONS_SPLIT/ for presentation/viva material and STUDY_NOTES_4_MEMBERS/ for full member explanations. Private input invoices and generated reports are omitted from Git; place your authorized test data in data/incoming. The provided integration script may expect those original fixture filenames.

## Original project notes

﻿# Jul26-SP1-L2-FA3_Pro-Group-11 — AI Invoice Auditor

Capstone submission: an end-to-end agentic AI system for automated multilingual invoice
processing, validation and auditing.

The project lives in [AI Invoice Auditor/](AI%20Invoice%20Auditor/). Start there —
its [README](AI%20Invoice%20Auditor/README.md) covers setup, architecture, agent design,
prompt templates, the API reference and the verification checks.

```bash
cd "AI Invoice Auditor"
cp .env.example .env     # fill in POSTGRES_PASSWORD (and AWS Bedrock keys if you have them)
docker compose up --build -d
```

| Surface | URL |
|---|---|
| Auditor dashboard | http://localhost:8501 |
| Agent API docs | http://localhost:8000/docs |
| Mock ERP | http://localhost:8001/docs |

## At a glance

* Six-container Docker Compose stack: `agent`, `mock-erp`, `streamlit-ui`, `postgres`, `qdrant`, `redis`
* Agents built on **two frameworks** — LangGraph and Google ADK — interoperating over the **A2A protocol**
* Eleven tools published over the **Model Context Protocol**, discovered at run time rather than imported
* **Agentic RAG** with Indexing, Retrieval, Augmentation, Generation and Reflection agents, gated on
  the RAG Triad (average > 0.70, up to 3 attempts)
* **Responsible AI guardrails** at every trust boundary and **LangFuse** tracing throughout
* PostgreSQL as the system of record, Qdrant as a rebuildable index, Redis as a disposable cache

# Temporary laptop architecture

```mermaid
flowchart LR
    Browser[Browser on localhost:8765] --> App[FastAPI laptop dashboard]
    Files[PDF / DOCX / PNG] --> App
    App --> Graph[LangGraph invoice workflow]
    Graph --> Parse[Text parsing / image transcription]
    Parse --> Translate[Detect language and translate]
    Translate --> Typed[Typed invoice extraction]
    Typed --> Check[YAML + Decimal validation]
    Check -->|HTTP| ERP[Local synthetic ERP routes]
    Check --> Report[Versioned report + human review]
    Report --> SQL[(SQLite originals / lines / feedback / stages)]
    Report --> Index[Local lexical vector index]
    Browser --> QA[Retrieve / rerank / generate / reflect]
    Index --> QA
    QA -->|Cited answer or abstention| Browser
    Translate --> Groq[Groq API - user key required]
    Typed --> Groq
    Report --> Groq
    QA --> Groq
```

This is the local development profile. The final HLD remains HLD_ARCHITECTURE.png with Bedrock, PostgreSQL, Qdrant, Redis, MCP and ADK/A2A. Local lexical vectors do not replace the final semantic-embedding requirement.

# Four-member ownership and presentation guide

Replace Member 1-4 with actual names. This is the proposed ownership and explanation allocation for the implemented code, not a fabricated record of who authored each change. Each person must read their files, run their demo and explain failure handling. The project was prepared collaboratively with coding assistance; use your course disclosure policy.

| Member | Area | Individual guide |
|---|---|---|
| 1 | Document intake, OCR, translation and contracts | members/MEMBER_1_DOCUMENT_INTELLIGENCE.md |
| 2 | ERP, deterministic validation and durable audit data | members/MEMBER_2_AUDIT_AND_DATA.md |
| 3 | Bedrock gateway, evidence RAG, embeddings and cache | members/MEMBER_3_RAG_AND_BEDROCK.md |
| 4 | UI, corrections, ADK/A2A, MCP integration and operations | members/MEMBER_4_INTEGRATION_AND_REVIEW.md |

## Shared explanation

An invoice is evidence. The model extracts/translates it, deterministic rules compare it to approved ERP records, and the system stores every original value and later reviewer correction. A report recommends approve/review/reject but does not authorize a payment. RAG answers only from saved evidence. PostgreSQL is the source of truth, Qdrant is rebuildable and Redis is disposable.

## Ten-minute group demo

1. Member 4: open UI and show six healthy services (1 minute).
2. Member 1: explain English PDF, Spanish DOCX and German scan; display raw/translated evidence (2 minutes).
3. Member 2: show Spanish price and German quantity discrepancies, Decimal arithmetic and ERP PO-1001 (2 minutes).
4. Member 3: ask one mismatch question with citations, a total question and an unsupported question (2 minutes).
5. Member 4: append a header correction, show version 1/version 2 and original history, then trace/export (2 minutes).
6. Each member states one limitation honestly: lab model permission, OCR accuracy, model-scored RAG confidence, or missing original dataset (1 minute).

Use completed reports if a temporary quota is exhausted; explain the saved failure and explicit resume. Do not claim a Groq demo proves Bedrock or a mocked SDK test proves live AWS. Record actual lab acceptance in ACCEPTANCE_CHECKLIST.md. Every member should know why there are six containers, why original data is immutable and how to resume without deleting history.

## Preparation checklist for every member

Read PROJECT_DOCUMENTATION.md and your individual guide. Trace a single invoice ID across the raw record, typed lines, report version and Qdrant evidence. Run three tests for your part. Prepare a 2-minute explanation and one failure example. Personalize member names in the deck and practice the handover to the next speaker. Screenshots must hide keys, tokens and personal invoice data.

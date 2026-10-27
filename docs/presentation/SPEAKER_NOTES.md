# Presentation speaker notes

## Slide 1

Member 1 introduces the document problem, Member 2 the deterministic audit, Member 3 grounded QA, Member 4 review and deployment. This is a capstone teaching implementation. All fixture data is synthetic. Replace member numbers with actual names before presenting.

## Slide 2

Member 4 explains service boundaries. Streamlit reads audit data in read-only transactions and writes through agent APIs. Agent uses LangGraph, real MCP stdio and Google ADK reporting via A2A. ERP lookups are HTTP only. PostgreSQL is the source of truth; Qdrant vectors are rebuildable; Redis is disposable. Bedrock and Langfuse are external dependencies, not extra containers.

## Slide 3

Member 1 explains direct text versus OCR and source language validation. Member 2 explains Decimal arithmetic and approved ERP values. Spanish BOX-01 price 120 compared to 100 is a 20% deviation. German quantity 12 compared to 10 is also 20%. Translation confidence is a self-assessment, not a calibrated probability. Original evidence and checkpoints remain saved after a failure.

## Slide 4

Member 3 explains fixed SQL intents versus semantic retrieval. Triad reflection checks answer relevance, context relevance and groundedness; average must be strictly greater than 0.7, with at most three retries after the first attempt. Canonical evidence excludes generated explanation prose. Member 4 demonstrates a header correction that creates version 2 without rewriting version 1 or original extraction, then exports HTML/JSON and shows a redacted trace.

## Slide 5

Development evidence: automated full dependency suite, real SDK protocol tests with stubbed model answers, six healthy Docker services, isolated retained-volume/reset checks and Langfuse smoke export/read-back. Do not call this live Nuvepro Bedrock verification. Model compatibility is documented: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-cohere-command-r-plus.html and MODEL_COMPATIBILITY.md. Original Masked Invoice.pdf and ERP SQL attachments were not supplied. Start with START_HERE_NUVEPRO.md and record actual lab results in ACCEPTANCE_CHECKLIST.md.
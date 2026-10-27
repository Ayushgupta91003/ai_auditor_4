# Member 4: Review interface and integration

## Your responsibility

Own Streamlit review/correction/export experience, ADK/A2A reporting, MCP integration boundaries, redacted observability and six-service deployment. Shared operations matter to everyone, but you coordinate the group demo and release checklist.

## Read these files in order

1. ui/app.py and agent/main.py: UI/API boundary, bearer token and report selection.
2. agent/reporting.py: Google ADK agent, A2A SDK adapter/card/client.
3. agent/mcp_client.py and mcp_server.py: stdio initialization, discovery and invocation.
4. agent/report_format.py and report_explanation.py: escaped HTML and currency guard.
5. agent/observability.py and scripts/check_langfuse.py: redacted spans and smoke read-back.
6. compose.yaml, the three Dockerfiles, scripts/setup_lab.py and START_HERE_NUVEPRO.md.
7. tests/test_a2a_sdk.py, test_local_api.py and test_report_format.py.

## Explain the flow

The UI reads audit data in read-only transactions and sends writes through authenticated agent APIs. A correction includes expected report version, reviewer and reason. The backend validates and saves feedback, makes an effective copy and inserts a new report. HTML/JSON exports use the saved report revision. The reporter is an ADK BaseAgent behind an actual A2A adapter; the workflow discovers its agent card and sends a task. MCP provides tools, while A2A delegates work between agents. Langfuse records redacted operation status.

```mermaid
sequenceDiagram
  participant U as Streamlit reviewer
  participant A as Agent API
  participant D as ADK via A2A
  participant P as PostgreSQL
  U->>A: Correct field + expected version + reason
  A->>P: Append feedback
  A->>A: Revalidate effective invoice
  A->>D: Explain deterministic report facts
  D-->>A: Explanation
  A->>P: Append versioned report
  A-->>U: New report; original retained
```

## Your two-minute speech

"My part connects the services and gives the reviewer control. Streamlit shows evidence, findings and all report versions. Corrections go through the agent API and retain the original extraction. We use MCP for tool discovery and calls, and A2A for delegating report explanation to a Google ADK agent. Six containers separate agent, UI, ERP, PostgreSQL, Qdrant and Redis. Database and vectors survive a normal restart; cache does not need to. Langfuse traces operation names without invoice content. The final deployment uses Bedrock, with the temporary local Groq mode clearly separate."

## Demo you own

Show six healthy services. Open English report and download HTML/JSON. Change header invoice_number with your name/reason, show version 2 and original version 1, and display feedback history. Explain a pending correction after a failed model call and its revalidate button. Show the A2A card through the supplied test/check command and a fresh Langfuse operation trace. Finish with limitations and team handoff.

## Three tests to explain

- Real ADK/A2A agent card, message/send and client response parsing with a synthetic model reply.
- API rejects missing session token/host attacks in local mode and preserves original extraction after correction.
- HTML escaping prevents document values from becoming executable markup; legacy reports can still export.

## Viva questions

**MCP versus A2A?** MCP lets an agent discover and call tools; A2A lets an agent discover another agent and delegate a task. Our code uses actual SDK protocols for both.

**What is durable?** Business history, original evidence, feedback and checkpoints in PostgreSQL; Qdrant vectors in a named volume. Redis and A2A in-memory task state are disposable.

**Why only six containers if Langfuse is required?** Use an external configured Langfuse endpoint; adding a self-hosted stack would add containers beyond the brief.

**What protects endpoints?** A runtime bearer service token. It is lab service authentication, not full employee SSO/TLS.

**Why separate lab instructions?** Company laptop localhost differs from lab localhost, and a lab role on the host may not reach a container. The guide checks runtime identity inside the agent.

**Can we say everything is fully verified?** No. Development SDK/infrastructure tests passed; Nuvepro model permissions, live answer quality and absent original dataset remain explicit acceptance boundaries.

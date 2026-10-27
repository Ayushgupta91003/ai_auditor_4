# Requirements and verification matrix

Implemented means code exists and was reviewed/tested at the listed boundary. It does not mean Nuvepro account permissions or the original absent dataset have been verified. Final deployment is the six-service Bedrock profile, not the temporary laptop profile.

| Requirement | Implementation / files | Verification and remaining boundary |
|---|---|---|
| Multilingual PDF/DOCX/scanned PNG | extraction.py, translation.py, models.py; OCR packs in image | English/Spanish/German local Groq screenshots; synthetic parser tests; lab Bedrock run pending |
| Bedrock Converse chat initialization | llm.py, settings.py | Real client + stubbed AWS response through LiteLLM tested; live lab pending |
| Model names in original brief | Configurable Nova Lite/Titan defaults | Exact retired Command R+ default changed; instructor disclosure required, see MODEL_COMPATIBILITY.md |
| LangGraph orchestration/resume | workflow.py, PostgreSQL checkpointer | Local workflow tests and actual PostgreSQL checkpoint durability passed |
| Real MCP tools | mcp_server.py, mcp_client.py | SDK initialize/list/call with real harvester passed |
| Google ADK and A2A | reporting.py | Actual ADK/A2A discovery/message/send/client parsing passed with stubbed model; live Bedrock reporting pending |
| In-process LiteLLM gateway | llm.py custom Converse provider | Stubbed real gateway test passed |
| ERP through HTTP | mock_erp/, validation.py | HTTP transport tests and live seed endpoint passed |
| Full extraction and typed persistence | repository.py, db/init.sql | SQL schema and isolated persistence checks passed |
| Completeness/arithmetic/matching rules | validation.py, configs/rules.yaml | Decimal/rule regression tests passed |
| Qdrant embeddings/recovery | rag.py, llm.embed | Real Qdrant persistence/recovery storage tested with synthetic vector; live Titan semantic indexing pending lab |
| Five-role RAG, reranking, triad/retry | rag.py, personas.yaml, prompts | Code and deterministic local tests; live lab answer quality pending |
| Structured SQL questions | bounded SQL intents in rag.py | Code/tests; lab acceptance checklist supplied |
| Human feedback with versions | corrections.py, repository.py, ui/app.py | Automated API original-preservation/version tests passed; lab manual demo pending |
| HTML/JSON download | report_format.py, Streamlit | User local export demo + escaping tests passed |
| Langfuse observability | observability.py, check_langfuse.py | Cloud auth/export/read-back passed; lab keys/network and new runtime spans pending |
| Six-container topology | compose.yaml + 3 Dockerfiles | All six healthy; live infrastructure smoke passed |
| PostgreSQL/Qdrant retained, Redis disposable | named volume configuration | Isolated down/up and own-test-volume reset checks passed |
| Image size/non-root/secret handling | Dockerfiles, ignore files | Development app image checks passed; final Linux UID permission setup added |
| Four balanced team portions | TEAM_MEMBER_GUIDE.md | Assigned ownership + walkthroughs/demo/viva; replace labels with actual names |
| HLD diagram and five-slide presentation | HLD_ARCHITECTURE.png, presentation/ | Project artifacts supplied; team should personalize names |
| Original Masked Invoice / ERP schema | Not supplied as separate attachments | Synthetic fixtures only; do not claim original dataset acceptance |
| Email ingestion | Design described in README | Design-only as allowed by supplied brief; no live mailbox integration claimed |

Release readiness: source, scripts and team documentation can be cloned from GitHub. Remaining external acceptance requires a Nuvepro lab session with suitable Docker, Bedrock permissions, available model IDs, network and actual supplied data. No claim of 100% course compliance should omit the model substitution and missing data boundary.

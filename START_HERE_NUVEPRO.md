# Start here: Nuvepro lab

Use the terminal of the Nuvepro lab machine. The company laptop can display the lab remotely; it does not have to run Docker itself. This guide is for the final Bedrock + PostgreSQL + Qdrant + Redis + MCP/A2A + Streamlit deployment. START_LOCAL.cmd is the separate temporary Groq laptop profile.

## 1. Clone and prepare

Required: Git, Python 3 (only the standard library for setup), Docker Engine with Compose v2, lab-approved network access for dependencies and AWS Bedrock. No Python packages need to be installed on the host for Docker deployment.

After configuring the lab model IDs/authentication below, Linux shortcut: `bash START_LAB.sh role` (or `env` / `profile`), then `bash CHECK_LAB.sh role` with the same mode. Start preserves existing private configuration. CHECK_LAB makes synthetic live model calls. Both stop on an error instead of claiming success. If your lab requires a proxy or role setup, use its provided terminal/session first.

```bash
git clone https://github.com/Ayushgupta91003/ai_auditor_4.git
cd ai_auditor_4
python3 scripts/setup_lab.py
```

Windows lab: use `python scripts/setup_lab.py` instead. Open `.env` privately in the lab editor. Setup generates matching random database credentials and a random service token, preserves an existing .env, and sets Linux UID/GID so the agent can write its bind-mounted incoming/reports folders. Run setup as the ordinary lab user. If the lab shell is root, create incoming/reports writable for the container UID 10001 and use LAB_UID=10001, LAB_GID=10001; do not run the agent as root.

Set AWS_REGION to the region provided by your lab, BEDROCK_MODEL/BEDROCK_RAG_MODEL to its permitted chat model or inference-profile ID, and BEDROCK_EMBED_MODEL to an available Titan V2 model. Keep LLM_PROVIDER=bedrock and EMBEDDING_PROVIDER=bedrock. Defaults are examples, not proof of account entitlement. Chat uses ChatBedrockConverse. Never commit .env. Do not put keys in .env.example or .env.local.example.

## 2. Select the lab's AWS authentication method

Do not create AWS access keys just for this project. Use the method Nuvepro provides. Nothing here changes IAM or the lab metadata service.

**A. Instance/workload role available inside Docker:** leave the three AWS key fields blank and start with plain compose below. The standard AWS SDK credential chain discovers the role. A role working on the host may be inaccessible inside Docker due to metadata networking; the doctor command checks the container.

**B. Temporary credentials already exported in the lab terminal:** use both files for all compose commands:

```bash
docker compose -f compose.yaml -f compose.aws-env.yaml up --build -d --wait
docker compose -f compose.yaml -f compose.aws-env.yaml exec -T agent python -m agent.lab_doctor
docker compose -f compose.yaml -f compose.aws-env.yaml exec -T agent python -m agent.bedrock_check
```

This forwards the existing AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_SESSION_TOKEN to the agent. It does not print or write them to source. If the lab provides temporary values in a console instead of exports, configure them privately in .env, including the session token, and use plain compose. Do not paste values in chat or screenshots. Renew credentials when the lab session expires; recreate the agent afterward.

**C. Shared AWS credentials/config profile:** use only if your lab actually supplies readable files. On Linux:

```bash
export AWS_SHARED_DIR="$HOME/.aws"
export AWS_PROFILE=default
docker compose -f compose.yaml -f compose.aws-profile.yaml up --build -d --wait
docker compose -f compose.yaml -f compose.aws-profile.yaml exec -T agent python -m agent.lab_doctor
```

The folder is mounted read-only. The container user must be allowed to read those files. The profile override does not install AWS CLI, credential_process executables or host SSO login helpers in the image. Profiles depending on those may require the lab's approved alternative. Do not copy credentials into the repository or Docker image.

## 3. Start the six services

For role authentication or private .env credentials:

```bash
docker compose up --build -d --wait
docker compose ps
docker compose exec -T agent python -m agent.lab_doctor
docker compose exec -T agent python -m agent.bedrock_check
```

For B/C above, retain the same two `-f` arguments when executing checks. Initial image downloads/builds need time and internet. All six services should be healthy. A healthy stack verifies infrastructure, not model permission or invoice accuracy. The Bedrock check makes synthetic billable chat/embedding requests and never falls back to Groq. `bash CHECK_LAB.sh role` also runs actual MCP discovery and a synthetic report request through A2A/ADK/Bedrock. Equivalent plain command: `docker compose exec -T agent python -m agent.protocol_smoke`.

Open port **8501** through Nuvepro's browser/port-preview feature. If the lab provides a desktop browser, try http://localhost:8501 there. Your company laptop's localhost is a different machine. Follow the lab's approved port access mechanism; do not expose a public unauthenticated proxy.

Host ports: UI 8501, agent 8000, mock ERP 8001, PostgreSQL 5432, Qdrant 6333, Redis 6379. If host 5432 is occupied, set POSTGRES_HOST_PORT=55432 in .env; internal DATABASE_URL still uses postgres:5432. Other conflicts require adjusting the matching host-side mapping in compose.yaml.

## 4. Configure Langfuse

Put LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL privately in lab .env. For the existing EU project, base URL is https://cloud.langfuse.com. These private values are intentionally absent from GitHub. Recreate agent after changes:

```bash
docker compose up -d --force-recreate agent
docker compose exec -T agent python -c "from langfuse import get_client; c=get_client(); print('Langfuse auth:', c.auth_check())"
```

Process an invoice, then refresh Langfuse Tracing. Operation spans are redacted; invoice text/prompts are not sent. Cloud tracing also needs lab network access. Use the same compose overrides if selected earlier. CHECK_LANGFUSE.cmd is for the Windows laptop environment, not a required lab command.

## 5. Run the acceptance demo

Upload one at a time in Streamlit:

| Input | Expected audit facts |
|---|---|
| samples/english.pdf | APPROVE; 0 findings; total 1210 EUR |
| samples/spanish.docx | REVIEW; line 1 unit_price 120 vs ERP 100; 20% deviation; total 1430 EUR |
| samples/german.png | REVIEW; line 1 quantity 12 vs ERP 10; 20% deviation; total 1430 EUR |

OCR/model output still needs verification on your lab model. Download HTML and JSON for each. Expand original extraction/history. Select Spanish, ask "Which unit price differs from the purchase order?" and inspect evidence/citations. Ask "What is the weather tomorrow?"; it should decline unsupported evidence. A scoped total question should return the selected invoice total through fixed SQL.

For a simple correction demo, change invoice_number on English to INV-ENGLISH-001-CORRECTED, line 0/header, reviewer your name, reason "Demonstrate reviewer correction". Expect version 2, original extraction retained, feedback recorded, and version 1 still selectable. Changing a numeric field alone does not automatically alter line/subtotals: arithmetic warnings are expected if dependent amounts become inconsistent.

If throttled, wait and use Resume on that record. Do not upload repeatedly. Do not delete audit history to hide failed attempts. Use docs/ACCEPTANCE_CHECKLIST.md to record actual lab results.

## 6. Stop, resume and update

```bash
docker compose down
docker compose up -d --wait
git pull --ff-only
docker compose up --build -d --wait
```

Use your chosen overrides consistently. Normal down retains named volumes. **Do not use down -v on your working project:** that erases PostgreSQL/Qdrant history. No reset is needed for the demo. Isolated storage testing is provided in scripts/verify_storage_docker.py for developers and creates/deletes only its own uniquely named test project.

## Troubleshooting

| Symptom | Next action |
|---|---|
| docker command unavailable/permission denied | Use a Docker-enabled lab machine; contact lab support for Docker access |
| lab_doctor cannot find credentials | Choose the lab's role/env/profile option; verify inside the agent, not only host |
| AccessDenied | Ask lab support to permit Converse/InvokeModel and the selected models/profile; do not replace with Groq |
| ExpiredToken | Renew the lab session/temporary credentials; recreate agent with updated environment |
| ResourceNotFound | Check region and allowed model/inference-profile IDs; see docs/MODEL_COMPATIBILITY.md |
| ValidationException about on-demand throughput | Use the lab-approved inference-profile ID where required |
| Upload permission denied | Run setup as normal Linux user; verify LAB_UID/GID and data/incoming + data/reports ownership |
| First build fails downloading packages | Confirm lab internet/package policy and Docker download access |
| UI unreachable | Open lab port 8501 via its preview, not company laptop localhost |
| Agent unhealthy | `docker compose logs --tail 60 agent`; redact any sensitive log content before sharing |
| Langfuse empty | Configure lab keys/base URL; recreate agent; make a new model call and refresh tracing |

## Release acceptance boundary

Local full dependency tests and Docker startup/storage checks passed on the development laptop. Live Bedrock and complete model-driven invoice acceptance in Nuvepro have not been executed from that lab. The exact retired model in the brief is replaced by configurable active Bedrock defaults; discuss this disclosed compatibility change with the instructor. Actual Masked Invoice.pdf and supplied ERP SQL were not provided, so the included dataset is synthetic. See docs/REQUIREMENTS_MATRIX.md for precise implementation versus verification status.

# Nuvepro handoff release

## Open these first

1. [START_HERE_NUVEPRO.md](../START_HERE_NUVEPRO.md): clone, private configuration, lab AWS role/env/profile options, startup, model checks and troubleshooting.
2. [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md): architecture, processing, storage, correction, RAG and integration explanation.
3. [TEAM_MEMBER_GUIDE.md](TEAM_MEMBER_GUIDE.md): balanced ownership, four individual guides, speaking notes, tests and viva questions.
4. [AI_Invoice_Auditor.pptx](presentation/AI_Invoice_Auditor.pptx): editable five-slide presentation with speaker notes. Personalize member names before presenting.
5. [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md): record actual lab results without secrets.

## Checks completed

- 76 automated tests passed, zero skipped in the full dependency environment. Model responses in automated SDK adapter tests are synthetic/stubbed.
- Six Docker services healthy after the final source update; live infrastructure smoke checks passed.
- Actual MCP and ADK/A2A SDK protocol tests passed. The supplied lab check also makes a live reporting call when run in the authorized lab.
- Isolated storage verification retained audit history, LangGraph checkpoints and Qdrant vectors through normal restart; Redis remained disposable. Reset checks deleted only the uniquely named test project's volumes.
- Langfuse authentication, non-sensitive smoke trace export and authenticated read-back passed on the development machine.
- Final five-slide deck rendered and visually inspected; package, layout and font checks passed. It was not opened in native PowerPoint.
- A fresh GitHub clone of code commit `6d940d5` contained the required source/docs/deck and no private env files. Setup generated private configuration, shell line endings were LF and Compose validation passed.
- Linux-specific setup was also exercised inside the non-root agent: UID mapping, data folder creation and env mode 0600 passed using disposable temporary files.
- Source credential scan passed before publication. Keys and runtime audit data remain outside Git.

## External acceptance still required

The developer cannot verify a Nuvepro account without access to that session. Run the container credential doctor, live Bedrock check and multilingual/Q&A/correction demo in that lab. Lab model access, temporary identity, networking and allowed inference profiles may need lab support. Host identity alone does not prove Docker can obtain credentials.

The original separate masked invoice and ERP schema attachments were not supplied; current fixtures are synthetic. The brief's retired Command R+ model is replaced by configurable active Bedrock defaults; see MODEL_COMPATIBILITY.md and disclose this compatibility change. These facts prevent a blanket claim that every original requirement has passed final course acceptance.

No further source coding task is intentionally deferred in this release. Any lab-specific fix should be based on the actual diagnostic result rather than inventing credentials or claiming a mocked test was live AWS.

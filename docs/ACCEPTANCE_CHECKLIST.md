# Lab acceptance record

Record the lab run date, region, non-secret model/profile IDs, Git commit and presenter names. Never record AWS/Langfuse secrets. These rows are intentionally unclaimed until someone runs them in Nuvepro.

| Check | Expected | Lab result / evidence |
|---|---|---|
| Clone and setup | Clean clone; generated private .env; no manual secret keys required if role works | Pending lab |
| Container startup | Six services healthy | Pending lab; development Docker passed |
| Credential doctor | Credential provider discovered inside agent | Pending lab |
| Live Bedrock check | Converse response + 1024-dimensional Titan vector | Pending lab |
| English digital PDF | APPROVE, 0 findings, EUR 1210 | Pending lab; local Groq user demo passed |
| Spanish DOCX | REVIEW; price 120 vs 100; 20% | Pending lab; local Groq user demo passed |
| German scanned PNG | REVIEW; qty 12 vs 10; 20% | Pending lab; local Groq user demo passed |
| Report exports | Readable HTML and valid JSON with correct ISO currency | Pending lab |
| Evidence QA | Correct mismatch with evidence identifiers | Pending lab |
| Unsupported question | Abstains without invented invoice facts | Pending lab |
| Header correction | Version 2; original and version 1 retained | Pending lab; automated API test passed |
| Duplicate file | Same checksum not a second audit | Pending lab; automated tests passed |
| Failure/resume | Retained stages; resume after permitted retry | Pending lab; automated tests passed |
| Langfuse | New redacted model-operation spans visible | Pending lab; cloud smoke passed |
| Normal down/up | History and vectors retained | Pending lab; isolated development Docker check passed |
| Original supplied dataset | Expected fields compared against actual supplied reference | Blocked: attachment not supplied |

Do not run down -v on working data. A lab run failure is useful evidence: retain the saved workflow, inspect its error, fix access/model/config and use resume. Exact extraction and prose can vary by allowed model; numerical expectations should not.

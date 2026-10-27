# Bedrock model compatibility

The final deployment uses AWS Bedrock only: ChatBedrockConverse for generation/translation/RAG through the in-process LiteLLM adapter, and Bedrock Titan InvokeModel for embeddings. Groq remains an explicitly separate temporary laptop-testing profile.

## Required correction to the supplied brief

The brief specifies Nova Lite and Cohere Command R+. AWS now states that Command R+ (`cohere.command-r-plus-v1:0`) reached end of life on **2026-08-19**, and requests fail with ResourceNotFoundException. It cannot remain a working default as of this project date (2026-10-27).

Source: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-cohere-command-r-plus.html

The current AWS model card lists Nova Lite as active. The default chat/translation/RAG selection is therefore `amazon.nova-lite-v1:0`, still on Bedrock, with a conservative configurable 4096-token output limit. This substitutes a supported AWS default for an unavailable model; it is not proof that the office account grants model access, and the substitution must be disclosed to the instructor if the exact retired model name is assessed.

Source: https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-lite.html

## Office/lab configuration

Set `BEDROCK_MODEL` and `BEDROCK_RAG_MODEL` to model IDs or inference-profile IDs explicitly available in the office account and region. If on-demand invocation requires a geographic inference profile, use that account's approved profile ID. Keep `LLM_PROVIDER=bedrock` and `EMBEDDING_PROVIDER=bedrock`. Never replace the final provider with Groq.

Run CHECK_BEDROCK.cmd after configuring runtime credentials/role, region and approved model IDs. It checks actual chat and Titan embeddings without sending private invoice data. Then run the real multilingual invoice acceptance cases on that account. Until those live checks pass, Bedrock account/model acceptance remains pending.

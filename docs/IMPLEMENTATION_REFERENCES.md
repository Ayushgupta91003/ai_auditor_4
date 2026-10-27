# API references checked during implementation

These are primary references for the adapters. Actual pinned-version runtime compatibility still requires the lab integration check.

- LangChain ChatBedrockConverse: https://docs.langchain.com/oss/python/integrations/chat/bedrock
- LiteLLM custom provider: https://docs.litellm.ai/docs/providers/custom_llm_server
- Google ADK 1.18 to_a2a adapter source: https://github.com/google/adk-python/blob/v1.18.0/src/google/adk/a2a/utils/agent_to_a2a.py
- A2A protocol documentation: https://a2a-protocol.org/

The current published A2A specification may differ from the pinned 0.3-compatible SDK. This build deliberately targets its pinned SDK/ADK protocol contract and must not be labeled A2A 1.0.

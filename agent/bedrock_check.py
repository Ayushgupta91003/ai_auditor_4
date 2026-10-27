"""Office/lab smoke test: actual Bedrock chat + embeddings, using runtime credentials only."""
from pathlib import Path
import sys
from agent.env import load_env
load_env(Path(__file__).resolve().parents[1]/".env")
from agent.settings import settings

def main():
    if settings.provider!="bedrock":raise SystemExit("Set LLM_PROVIDER=bedrock for the final lab profile; this check never falls back to Groq.")
    from agent.llm import ask,embed
    try:
        answer=ask("This is a connectivity test. Reply only READY.","Reply READY without any additional content.",model=settings.model)
        if not answer.strip():raise ValueError("Empty chat response")
        print("Bedrock Converse generation: response received",flush=True)
        vector=embed("Synthetic connectivity test invoice total EUR 100")
        if len(vector)!=1024:raise ValueError("Unexpected embedding dimension")
        print("Bedrock Titan embeddings: 1024 dimensions received",flush=True)
    except Exception as error:
        raise SystemExit("Bedrock check failed ("+type(error).__name__+"). Verify runtime AWS credentials/role, region and access to the configured model IDs. No Groq fallback was used.") from None
    if __import__("os").getenv("LANGFUSE_PUBLIC_KEY"):
        from langfuse import get_client
        get_client().flush()
    print("Live Bedrock connectivity checks passed. Full invoice acceptance and model output accuracy must still be tested.")
if __name__=="__main__":main()

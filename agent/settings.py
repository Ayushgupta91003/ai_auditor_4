import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
class Settings:
    provider = os.getenv("LLM_PROVIDER", "bedrock").lower()
    groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    database_url = os.getenv("DATABASE_URL", "postgresql://auditor:change-me@postgres:5432/invoices")
    erp_url = os.getenv("ERP_URL", "http://mock-erp:8000")
    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    a2a_url = os.getenv("A2A_URL", "http://agent:8000/reporting")
    incoming = Path(os.getenv("INCOMING_DIR", str(ROOT / "data/incoming")))
    reports = Path(os.getenv("REPORTS_DIR", str(ROOT / "data/reports")))
    model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b") if provider == "groq" else os.getenv("BEDROCK_MODEL", "amazon.nova-lite-v1:0")
    rag_model = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b") if provider == "groq" else (os.getenv("BEDROCK_RAG_MODEL") or model)
    max_output_tokens = int(os.getenv("BEDROCK_MAX_OUTPUT_TOKENS", "4096"))
    embedding_model = os.getenv("BEDROCK_EMBED_MODEL", "amazon.titan-embed-text-v2:0")
    region = os.getenv("AWS_REGION", "us-east-1")
    watch = os.getenv("WATCH_ENABLED", "true").lower() == "true"
settings = Settings()

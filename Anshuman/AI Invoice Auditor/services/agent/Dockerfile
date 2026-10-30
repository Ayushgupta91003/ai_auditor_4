FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# OCR + PDF tooling. Tesseract with the language packs the dataset actually needs
# (English, Spanish, German) plus Poppler for pdf2image PDF rendering.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
        gosu \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-spa \
        tesseract-ocr-deu \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer -- rebuilt only when requirements.txt changes
COPY services/agent/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Application code and shared config
COPY services/agent/ /app/services/agent/
COPY config/ /app/config/

# Runtime dirs (owned by the unprivileged user so bind-mounts still work)
RUN mkdir -p /app/data/incoming /app/outputs/reports \
    && groupadd --system --gid 1001 appuser \
    && useradd  --system --uid 1001 --gid 1001 --home /app --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app \
    && sed -i 's/\r$//' /app/services/agent/entrypoint.sh \
    && chmod +x /app/services/agent/entrypoint.sh

# The entrypoint fixes bind-mount ownership as root, then drops to appuser.
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/services/agent/entrypoint.sh"]
CMD ["uvicorn", "services.agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

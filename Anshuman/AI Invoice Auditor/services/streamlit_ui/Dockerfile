FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY services/streamlit_ui/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/streamlit_ui/ /app/services/streamlit_ui/

RUN groupadd --system --gid 1001 appuser \
    && useradd  --system --uid 1001 --gid 1001 --home /app --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

# --server.address=0.0.0.0 is required or the port cannot be reached from the host.
CMD ["streamlit", "run", "services/streamlit_ui/app.py", "--server.port=8501", "--server.address=0.0.0.0"]

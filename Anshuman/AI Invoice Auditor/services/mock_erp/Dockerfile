FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq-dev / build-essential are needed to compile psycopg2-binary wheels on some archs;
# curl is used by the container healthcheck. Removed from apt lists to keep the image small.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY services/mock_erp/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY services/mock_erp/ /app/services/mock_erp/
COPY data/ERP_mockdata/ /app/data/ERP_mockdata/

RUN groupadd --system --gid 1001 appuser \
    && useradd  --system --uid 1001 --gid 1001 --home /app --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "services.mock_erp.main:app", "--host", "0.0.0.0", "--port", "8000"]

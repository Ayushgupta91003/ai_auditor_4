FROM python:3.11.14-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa tesseract-ocr-deu poppler-utils && rm -rf /var/lib/apt/lists/*
COPY agent/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-compile -r requirements.txt
RUN useradd --create-home --uid 10001 app
COPY agent ./agent
COPY configs ./configs
RUN mkdir -p data/incoming data/reports && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

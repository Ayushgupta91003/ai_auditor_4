FROM python:3.11.14-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY mock_erp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home --uid 10001 app
COPY mock_erp ./mock_erp
USER app
EXPOSE 8000
CMD ["uvicorn", "mock_erp.main:app", "--host", "0.0.0.0", "--port", "8000"]

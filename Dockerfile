FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir .

ENV PYTHONUNBUFFERED=1

CMD ["sh", "-c", "uvicorn saas_job_api.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]

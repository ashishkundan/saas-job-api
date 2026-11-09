# SaaS Job API image (Azure Container Apps; also runs the Alembic migration job).
#
# Base pinned by digest (the tag is informational) - bump deliberately.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# Debian security fixes released after the pinned base was built.
RUN apt-get update && apt-get -y --no-install-recommends upgrade \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin api

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic

RUN pip install --no-cache-dir ".[migrations]"

ENV PYTHONUNBUFFERED=1
USER 10001:10001

CMD ["sh", "-c", "uvicorn saas_job_api.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]

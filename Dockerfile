# One image for the web server and the worker.
# See expansion/agent-spec/create-environment.md.

FROM python:3.14-slim AS base
# git: the server clones submissions. sqlite3: for inspecting the database.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git sqlite3 \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS dev
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
# Source is bind-mounted by compose.yaml, not copied.

FROM base AS prod
# Filled in at deployment (expansion/agent-spec/deploy.md): copy the source
# and compiled JS, run as a non-root user, start gunicorn.

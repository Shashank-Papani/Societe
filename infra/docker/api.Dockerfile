# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# ffmpeg/ffprobe are the local stand-in for MediaConvert. Pillow ships manylinux
# wheels, so no image codec headers are needed at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential libpq-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/api/app services/api/app
# Workers share the API codepath; they are plain packages on PYTHONPATH.
COPY services/workers services/workers

RUN uv sync --frozen --package societe-api --no-dev

WORKDIR /app/services/api

COPY infra/docker/api.entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

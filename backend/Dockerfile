# syntax=docker/dockerfile:1.7
# One image for every backend process (api, worker, beat, flower, migrations).

# ---- Build stage: install the locked dependencies into a virtualenv ------------
FROM python:3.13-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /code
COPY pyproject.toml uv.lock ./
# --frozen: install exactly what uv.lock says (hash-checked); never re-resolve in the image.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Runtime stage: slim image without build tooling, non-root user -------------
FROM python:3.13-slim-trixie
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /code app \
    # Upload storage. A named volume mounted here inherits this ownership.
    && mkdir -p /data/uploads && chown app:app /data/uploads
COPY --from=builder /opt/venv /opt/venv
WORKDIR /code
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

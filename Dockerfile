# ── Stage 1: Python runtime base ───────────────────────────────────────────────
FROM python:3.11-slim AS backend-base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY backend/pyproject.toml backend/uv.lock ./backend/
WORKDIR /app/backend
ENV UV_PROJECT_ENVIRONMENT=/app/backend/venv
RUN uv sync --frozen --no-cache
ENV PATH="/app/backend/venv/bin:${PATH}"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]


# ── Stage 2: Production image ───────────────────────────────────────────────────
# 打包前须在宿主机（或 CI）先编译前端：
#   cd frontend && npm ci && npm run build
# 再执行：
#   docker build --target production -t banana-music:latest .
FROM backend-base AS production

WORKDIR /app

COPY backend/ ./backend/
COPY plugins/ ./plugins/
COPY scripts/ ./scripts/
COPY frontend/dist ./frontend/dist

RUN mkdir -p /app/data/resource

WORKDIR /app/backend

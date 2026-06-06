# ============================================================================
# AI Werewolf — Multi-stage production Dockerfile
# ============================================================================
# Stage 1: Frontend build
# ============================================================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps 2>/dev/null || npm install --legacy-peer-deps

COPY frontend/ ./
RUN npm run build

# ============================================================================
# Stage 2: Backend dependencies
# ============================================================================
FROM python:3.12-slim AS backend-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# ============================================================================
# Stage 3: Production runtime
# ============================================================================
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash werewolf \
    && mkdir -p /app /app/data /app/outputs \
    && chown -R werewolf:werewolf /app

WORKDIR /app

# Copy Python packages from backend-base
COPY --from=backend-base /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=backend-base /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=werewolf:werewolf backend/ ./backend/
COPY --chown=werewolf:werewolf configs/ ./configs/
COPY --chown=werewolf:werewolf scripts/ ./scripts/

# Copy built frontend from Stage 1
COPY --from=frontend-builder --chown=werewolf:werewolf /build/frontend/.next ./frontend/.next
COPY --from=frontend-builder --chown=werewolf:werewolf /build/frontend/public ./frontend/public
COPY --from=frontend-builder --chown=werewolf:werewolf /build/frontend/package.json ./frontend/package.json
COPY --from=frontend-builder --chown=werewolf:werewolf /build/frontend/node_modules ./frontend/node_modules

# Entrypoint
COPY --chown=werewolf:werewolf scripts/docker-entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

USER werewolf

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -sf http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["entrypoint"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]

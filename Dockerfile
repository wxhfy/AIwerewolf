# AI Werewolf — Backend production Dockerfile
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
# Runtime
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

# Entrypoint
COPY --chown=werewolf:werewolf scripts/docker-entrypoint.sh /usr/local/bin/entrypoint
RUN chmod +x /usr/local/bin/entrypoint

USER werewolf

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -sf http://127.0.0.1:8000/api/health || exit 1

ENTRYPOINT ["entrypoint"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]

#!/bin/bash
# ============================================================================
# AI Werewolf — Docker Entrypoint
# ============================================================================
set -euo pipefail

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🐺  AI Werewolf — Starting..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# --- Wait for PostgreSQL ---
if [ -n "${DATABASE_URL:-}" ]; then
    echo "⏳  Waiting for PostgreSQL..."
    ATTEMPTS=0
    MAX_ATTEMPTS=30
    until python -c "
import os, psycopg2
url = os.environ.get('DATABASE_URL', '')
if url:
    conn = psycopg2.connect(url)
    conn.close()
    print('connected')
" 2>/dev/null; do
        ATTEMPTS=$((ATTEMPTS + 1))
        if [ $ATTEMPTS -ge $MAX_ATTEMPTS ]; then
            echo "❌  PostgreSQL did not become ready in time"
            break
        fi
        sleep 2
    done
    echo "✅  PostgreSQL ready"
fi

# --- Run DB migrations ---
if [ "${AUTO_MIGRATE:-true}" = "true" ]; then
    echo "🔄  Running database migrations..."
    python -c "from backend.db.database import init_db; init_db(); print('Schema applied')" || echo "⚠️  Migration skipped (DB may not be ready)"
fi

# --- Run preflight ---
echo "🔍  Running preflight checks..."
python -c "from backend.ops.preflight import run_preflight; r = run_preflight(); print(f'Preflight: {\"PASS\" if r[\"all_pass\"] else \"WARN\"}')" || echo "⚠️  Preflight skipped"

# --- Show config ---
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀  Starting server..."
echo "    LLM Provider : ${LLM_PROVIDER:-default}"
echo "    Database     : ${DATABASE_URL:-sqlite}"
echo "    Strict Mode  : ${AIWEREWOLF_STRICT_MODE:-false}"
echo "    Allow Fallbk : ${ALLOW_FALLBACK:-false}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exec "$@"

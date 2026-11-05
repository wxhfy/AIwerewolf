#!/bin/bash
# WARNING: box / local-dev helper ONLY. Not for production or CI.
# Hard-coded defaults target the shared /workspace box layout; override via env.
# Secrets are sourced from SECRET_ENV_FILE (never embed keys in this script).
#
# Logs (under AIWEREWOLF_ROOT): run.log, worker.log, analysis.log, frontend.log
# PIDs (under RUN_DIR): api.pid, match_worker.pid, analysis_worker.pid, frontend.pid
set -euo pipefail

AIWEREWOLF_ROOT="${AIWEREWOLF_ROOT:-/workspace/AIwerewolf}"
PG_BIN="${PG_BIN:-/workspace/pgbin/node_modules/@embedded-postgres/linux-x64/native/bin}"
PGDATA="${PGDATA:-/workspace/pgdata}"
PGPORT="${PGPORT:-5433}"
PG_LOG="${PG_LOG:-/workspace/pgdata.log}"
PG_SOCKET_DIR="${PG_SOCKET_DIR:-/tmp}"
SECRET_ENV_FILE="${SECRET_ENV_FILE:-/home/box/.secrets/siliconflow.env}"
API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3001}"
RUN_DIR="${RUN_DIR:-${AIWEREWOLF_ROOT}/.run}"

cd "$AIWEREWOLF_ROOT"
mkdir -p "$RUN_DIR"

stop_pidfile() {
  local pidfile="$1"
  local label="$2"
  if [ -f "$pidfile" ]; then
    local pid
    pid="$(tr -d '[:space:]' < "$pidfile" || true)"
    if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then
      echo "Stopping $label (pid $pid)"
      kill "$pid" 2>/dev/null || true
      # brief wait then force if needed
      for _ in 1 2 3 4 5; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.2
      done
      if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    fi
    rm -f "$pidfile"
  fi
}

# Prefer stopping only processes this script previously started (PID files).
stop_pidfile "$RUN_DIR/api.pid" "api"
stop_pidfile "$RUN_DIR/match_worker.pid" "match_worker"
stop_pidfile "$RUN_DIR/analysis_worker.pid" "analysis_worker"
stop_pidfile "$RUN_DIR/frontend.pid" "frontend"

# Start embedded Postgres if present and not already running.
if [ -x "$PG_BIN/pg_ctl" ] && [ -d "$PGDATA" ]; then
  "$PG_BIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1 \
    || "$PG_BIN/pg_ctl" -D "$PGDATA" -o "-p ${PGPORT} -k ${PG_SOCKET_DIR}" -l "$PG_LOG" start
fi

set -a
if [ -f ./.env ]; then
  # shellcheck disable=SC1091
  . ./.env
fi
if [ -f "$SECRET_ENV_FILE" ]; then
  # strip CR in case the secret file was edited on Windows
  # shellcheck disable=SC1091
  . <(tr -d '\r' < "$SECRET_ENV_FILE")
fi
set +a

if [ -z "${SILICONFLOW_API_KEY:-}" ] && [ "${LLM_PROVIDER:-}" = "siliconflow" ]; then
  echo "ERROR: SILICONFLOW_API_KEY missing. Put it in ${SECRET_ENV_FILE}" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "ERROR: missing .venv under ${AIWEREWOLF_ROOT}" >&2
  exit 1
fi

.venv/bin/python -c "from backend.db.database import init_db; init_db()"
: > run.log; : > worker.log; : > analysis.log; : > frontend.log

nohup .venv/bin/uvicorn backend.app:app --host "$API_HOST" --port "$API_PORT" > run.log 2>&1 &
echo $! > "$RUN_DIR/api.pid"

nohup .venv/bin/python -m backend.workers.match_worker > worker.log 2>&1 &
echo $! > "$RUN_DIR/match_worker.pid"

ANALYSIS_FLAG=$(echo "${ANALYSIS_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$ANALYSIS_FLAG" = "1" ] || [ "$ANALYSIS_FLAG" = "true" ] || [ "$ANALYSIS_FLAG" = "yes" ] || [ "$ANALYSIS_FLAG" = "on" ]; then
  nohup .venv/bin/python -m backend.workers.analysis_worker > analysis.log 2>&1 &
  echo $! > "$RUN_DIR/analysis_worker.pid"
  ANALYSIS_STATUS=on
else
  echo "ANALYSIS_ENABLED=false — analysis worker not started" > analysis.log
  ANALYSIS_STATUS=off
fi

(
  cd frontend
  PORT="$FRONTEND_PORT" nohup npm run start -- -p "$FRONTEND_PORT" > ../frontend.log 2>&1 &
  echo $! > "$RUN_DIR/frontend.pid"
)

echo "Started. Frontend :${FRONTEND_PORT}  API ${API_HOST}:${API_PORT}  provider=${LLM_PROVIDER:-} model=${SILICONFLOW_MODEL:-} analysis=${ANALYSIS_STATUS}"
echo "PIDs under ${RUN_DIR}; stop with: kill \$(cat ${RUN_DIR}/*.pid)"

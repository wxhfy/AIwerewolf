#!/bin/bash
# Start full AIwerewolf stack. Logs: run.log, worker.log, analysis.log, frontend.log
# SILICONFLOW_API_KEY is sourced from /home/box/.secrets/siliconflow.env (not committed).
set -euo pipefail
cd /workspace/AIwerewolf
B=/workspace/pgbin/node_modules/@embedded-postgres/linux-x64/native/bin
$B/pg_ctl -D /workspace/pgdata status >/dev/null || $B/pg_ctl -D /workspace/pgdata -o "-p 5433 -k /tmp" -l /workspace/pgdata.log start

# Stop previous app processes (keep postgres)
pkill -f '/workspace/AIwerewolf/.venv/bin/uvicorn backend.app:app' 2>/dev/null || true
pkill -f 'python -m backend.workers.match_worker' 2>/dev/null || true
pkill -f 'python -m backend.workers.analysis_worker' 2>/dev/null || true
# next-server for this app (port 3001)
if command -v fuser >/dev/null 2>&1; then
  fuser -k 8000/tcp 2>/dev/null || true
  fuser -k 3001/tcp 2>/dev/null || true
else
  pids=$(ss -ltnp 2>/dev/null | awk '/:(8000|3001) /{print}' | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | sort -u)
  for p in $pids; do kill "$p" 2>/dev/null || true; done
fi
sleep 1

set -a
. ./.env
if [ -f /home/box/.secrets/siliconflow.env ]; then
  # strip CR in case the secret file was edited on Windows
  set -a
  . <(tr -d '\r' < /home/box/.secrets/siliconflow.env)
  set +a
fi
set +a

if [ -z "${SILICONFLOW_API_KEY:-}" ] && [ "${LLM_PROVIDER:-}" = "siliconflow" ]; then
  echo "ERROR: SILICONFLOW_API_KEY missing. Put it in /home/box/.secrets/siliconflow.env" >&2
  exit 1
fi

.venv/bin/python -c "from backend.db.database import init_db; init_db()"
: > run.log; : > worker.log; : > analysis.log; : > frontend.log
nohup .venv/bin/uvicorn backend.app:app --host 0.0.0.0 --port 8000 > run.log 2>&1 &
nohup .venv/bin/python -m backend.workers.match_worker > worker.log 2>&1 &
ANALYSIS_FLAG=$(echo "${ANALYSIS_ENABLED:-false}" | tr '[:upper:]' '[:lower:]')
if [ "$ANALYSIS_FLAG" = "1" ] || [ "$ANALYSIS_FLAG" = "true" ] || [ "$ANALYSIS_FLAG" = "yes" ] || [ "$ANALYSIS_FLAG" = "on" ]; then
  nohup .venv/bin/python -m backend.workers.analysis_worker > analysis.log 2>&1 &
  ANALYSIS_STATUS=on
else
  echo "ANALYSIS_ENABLED=false — analysis worker not started" > analysis.log
  ANALYSIS_STATUS=off
fi
cd frontend && PORT=3001 nohup npm run start -- -p 3001 > ../frontend.log 2>&1 &
echo "Started. Frontend :3001  API :8000  provider=${LLM_PROVIDER} model=${SILICONFLOW_MODEL:-} analysis=${ANALYSIS_STATUS}"

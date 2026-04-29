#!/usr/bin/env bash
# Sobe os processos do app (hoje: serve.py local). Idempotente.
# Registra PIDs em .app-state.json para o stop.sh saber o que matar.
# Quando o app ganhar mais processos (worker Stockfish nativo, fila), entram aqui.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE_FILE=".app-state.json"
PORT="${CHESS_SCOUT_PORT:-8000}"
HOST="${CHESS_SCOUT_HOST:-127.0.0.1}"
URL="http://${HOST}:${PORT}/"
PYTHON="${CHESS_SCOUT_PYTHON:-/opt/homebrew/bin/python3.12}"
LOG_DIR=".app-logs"
mkdir -p "$LOG_DIR"

is_alive() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# Se já existe estado e o processo ainda está vivo + API responde, é idempotente.
if [ -f "$STATE_FILE" ]; then
  EXISTING_PID="$(/usr/bin/python3 -c "import json,sys; d=json.load(open('$STATE_FILE'));
print(d.get('processes',{}).get('serve',{}).get('pid','') or '')" 2>/dev/null || echo "")"
  if is_alive "$EXISTING_PID" && curl -fsS "${URL}api/health" >/dev/null 2>&1; then
    echo "♞  app já está rodando (PID $EXISTING_PID)"
    echo "   web: $URL"
    exit 0
  fi
  # Estado obsoleto, limpa
  rm -f "$STATE_FILE"
fi

echo "▶ subindo serve.py em $URL …"
LOG_FILE="$LOG_DIR/serve.$(date +%Y%m%d-%H%M%S).log"
nohup "$PYTHON" scripts/serve.py --port "$PORT" --host "$HOST" \
  > "$LOG_FILE" 2>&1 &
SERVE_PID=$!

# Aguarda API responder (max 10s)
for i in $(seq 1 20); do
  if curl -fsS "${URL}api/health" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
  if ! is_alive "$SERVE_PID"; then
    echo "❌ serve.py morreu durante a inicialização. Veja $LOG_FILE"
    exit 1
  fi
done

if ! curl -fsS "${URL}api/health" >/dev/null 2>&1; then
  echo "❌ API não respondeu em 10s. Veja $LOG_FILE"
  kill "$SERVE_PID" 2>/dev/null || true
  exit 1
fi

# Grava estado
/usr/bin/python3 - <<PY
import json, os, datetime
state = {
    "started_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "processes": {
        "serve": {"pid": $SERVE_PID, "url": "$URL", "log": "$LOG_FILE"},
    },
}
with open("$STATE_FILE", "w") as f:
    json.dump(state, f, indent=2)
PY

echo "✅ app no ar"
echo "   web : $URL"
echo "   api : ${URL}api/health"
echo "   pid : $SERVE_PID"
echo "   log : $LOG_FILE"
echo "   stop: scripts/stop.sh"

# Tenta abrir o navegador (best-effort, silencioso se falhar)
if command -v open >/dev/null 2>&1; then
  open "$URL" >/dev/null 2>&1 || true
fi

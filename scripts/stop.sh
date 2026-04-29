#!/usr/bin/env bash
# Derruba todos os processos registrados em .app-state.json e limpa o arquivo.
# Idempotente: se nada está rodando, sai com sucesso silencioso.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STATE_FILE=".app-state.json"

if [ ! -f "$STATE_FILE" ]; then
  echo "ℹ  nada para parar (nenhum .app-state.json)"
  # Defensivo: mata serve.py em portas conhecidas se sobrou processo órfão
  ORPHANS="$(pgrep -f "scripts/serve.py" 2>/dev/null || true)"
  if [ -n "$ORPHANS" ]; then
    echo "⚠ processos órfãos serve.py encontrados: $ORPHANS"
    echo "  matando…"
    pkill -f "scripts/serve.py" 2>/dev/null || true
  fi
  exit 0
fi

# Lê PIDs e mata um por um
killed=0
total=0
while IFS= read -r line; do
  total=$((total + 1))
  IFS=':' read -r name pid <<<"$line"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null && {
      echo "✅ parado: $name (PID $pid)"
      killed=$((killed + 1))
    } || echo "⚠ falha ao matar $name (PID $pid)"
  else
    echo "ℹ  $name (PID $pid) já estava parado"
  fi
done < <(/usr/bin/python3 -c "
import json
with open('$STATE_FILE') as f:
    d = json.load(f)
for name, proc in (d.get('processes') or {}).items():
    pid = proc.get('pid', '')
    print(f'{name}:{pid}')
")

# Aguarda graceful shutdown
sleep 1

# Se algum sobreviveu, força
while IFS= read -r line; do
  IFS=':' read -r name pid <<<"$line"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    echo "⚠ $name (PID $pid) ainda vivo — SIGKILL"
    kill -9 "$pid" 2>/dev/null || true
  fi
done < <(/usr/bin/python3 -c "
import json
with open('$STATE_FILE') as f:
    d = json.load(f)
for name, proc in (d.get('processes') or {}).items():
    pid = proc.get('pid', '')
    print(f'{name}:{pid}')
")

rm -f "$STATE_FILE"
echo "✅ app derrubado ($killed/$total processos parados)"

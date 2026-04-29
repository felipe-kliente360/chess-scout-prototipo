---
name: assess-data
description: Inspeciona `data/db/history.db` e gera resumo do estado da base — quais jogadores há, status das 3 camadas de análise (tática, estratégica via position_facts, tempo via clock_ms), profundidade Stockfish, cobertura ECO. Saída em PT-BR direto, com diagnóstico de "o que dá pra rodar agora" para cada user.
---

# Skill: assess-data

## Objetivo

Mostrar de uma vez o estado da base local: jogadores armazenados, quantidade e tipo de partidas, cobertura das camadas analíticas, e diagnóstico de qual relatório pode rodar imediatamente para cada um. Sem argumentos.

## Fluxo

### 1. Garantir DB existe

```bash
test -f data/db/history.db || { echo "❌ data/db/history.db não existe — rode /app-start e faça uma coleta primeiro."; exit 1; }
```

### 2. Coletar métricas via SQL

Use uma única passagem com Python para evitar 10 chamadas separadas. Rode o snippet abaixo via Bash:

```bash
/opt/homebrew/bin/python3.12 - <<'PY'
import sqlite3, json
from pathlib import Path
db = Path("data/db/history.db")
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

# 1. Players + ciclos
players = [dict(r) for r in conn.execute(
    "SELECT username, first_seen, last_seen, total_cycles FROM players ORDER BY last_seen DESC"
).fetchall()]

# 2. Métricas por user (uma query agregada)
rows = conn.execute("""
  SELECT
    g.username AS u,
    COUNT(DISTINCT g.game_id) AS n_games,
    COUNT(DISTINCT CASE WHEN ga.ply IS NOT NULL THEN g.game_id END) AS games_analyzed,
    COUNT(ga.ply) AS plies_total,
    SUM(CASE WHEN ga.tactical_theme IS NOT NULL AND ga.tactical_theme != '' THEN 1 ELSE 0 END) AS plies_w_tactical,
    SUM(CASE WHEN ga.position_facts IS NOT NULL AND ga.position_facts != '' THEN 1 ELSE 0 END) AS plies_w_facts,
    SUM(CASE WHEN ga.clock_ms IS NOT NULL THEN 1 ELSE 0 END) AS plies_w_clock,
    MIN(ga.depth) AS depth_min,
    MAX(ga.depth) AS depth_max,
    COUNT(DISTINCT g.time_class) AS n_time_classes,
    COUNT(DISTINCT CASE WHEN g.eco IS NOT NULL AND g.eco != '' THEN g.game_id END) AS games_w_eco
  FROM games g
  LEFT JOIN game_analyses ga ON ga.game_id = g.game_id
  GROUP BY g.username
""").fetchall()
metrics = {r["u"]: dict(r) for r in rows}

# 3. Time classes por user
tc = conn.execute("""
  SELECT username, time_class, COUNT(*) AS n FROM games
  GROUP BY username, time_class
""").fetchall()
tc_by_user = {}
for r in tc:
    tc_by_user.setdefault(r["username"], {})[r["time_class"] or "(sem)"] = r["n"]

# 4. Última análise (cycle stamp) e perspective
last_cycle = conn.execute("""
  SELECT username, MAX(stamp) AS stamp, perspective
  FROM analyses GROUP BY username
""").fetchall()
last_by_user = {r["username"]: dict(r) for r in last_cycle}

# 5. Position cache (tamanho global)
cache = conn.execute("SELECT COUNT(*) AS n, MIN(depth) AS dmin, MAX(depth) AS dmax FROM position_cache").fetchone()

print("=" * 78)
print(f"📊 BASE: {db}  ({db.stat().st_size / 1024 / 1024:.1f} MB)")
print(f"   position_cache: {cache['n']} posições (depth {cache['dmin']}–{cache['dmax']})")
print("=" * 78)

if not players:
    print("\n(sem jogadores — base vazia)")
    raise SystemExit(0)

for p in players:
    u = p["username"]
    m = metrics.get(u, {})
    tcs = tc_by_user.get(u, {})
    last = last_by_user.get(u, {})

    n_games = m.get("n_games", 0)
    plies = m.get("plies_total", 0)
    games_analyzed = m.get("games_analyzed", 0)
    pct_analyzed = (100 * games_analyzed / n_games) if n_games else 0

    pct_tactical = (100 * (m.get("plies_w_tactical") or 0) / plies) if plies else 0
    pct_facts = (100 * (m.get("plies_w_facts") or 0) / plies) if plies else 0
    pct_clock = (100 * (m.get("plies_w_clock") or 0) / plies) if plies else 0
    pct_eco = (100 * (m.get("games_w_eco") or 0) / n_games) if n_games else 0

    # diagnóstico
    can_report = games_analyzed >= 10
    confidence_hint = "alta" if games_analyzed >= 30 else ("média" if games_analyzed >= 15 else "baixa")
    depth_min = m.get("depth_min")
    depth_max = m.get("depth_max")
    depth_str = f"{depth_min}" if depth_min == depth_max else f"{depth_min}–{depth_max}"

    print(f"\n▶ {u}  · {n_games} partidas · {p['total_cycles']} ciclo(s) gerados")
    tcs_str = ", ".join(f"{k}={v}" for k, v in sorted(tcs.items()))
    print(f"    ritmos:        {tcs_str}")
    print(f"    análise SF:    {games_analyzed}/{n_games} partidas ({pct_analyzed:.0f}%) · depth {depth_str} · {plies} plies")
    print(f"    camada tática: {pct_tactical:.1f}% dos plies com fingerprint tático")
    print(f"    camada estrut: {pct_facts:.1f}% dos plies com position_facts cacheados")
    print(f"    camada tempo:  {pct_clock:.1f}% dos plies com relógio extraído (daily fica vazio por design)")
    print(f"    cobertura ECO: {pct_eco:.0f}% das partidas classificadas")
    if last:
        print(f"    último ciclo:  stamp={last.get('stamp')} perspective={last.get('perspective') or '—'}")

    # Diagnóstico
    if not can_report:
        print(f"    ⚠ não dá pra gerar relatório útil ainda ({games_analyzed} partidas analisadas, mínimo prático ≥10).")
    else:
        msg = f"    ✅ pronto: /report-myself {u}  ou  /report-enemy {u}  (confiança esperada: {confidence_hint})"
        print(msg)
        # extras
        if pct_clock < 30 and any(tc != "daily" for tc in tcs):
            print(f"    💡 tempo ainda escasso ({pct_clock:.0f}%); rode compute.py uma vez pra forçar backfill do %clk no DB.")
        if pct_facts < 30:
            print(f"    💡 fatos estruturais ainda escassos ({pct_facts:.0f}%); 1 ciclo de compute popula o cache.")
        if depth_min and depth_min < 12:
            print(f"    💡 depth mínimo {depth_min} é raso pra meio-jogo. Reanalise com depth ≥15 pra precisão melhor.")

print()
print("=" * 78)
print(f"Total: {len(players)} jogador(es). Pra detalhar um: sqlite3 {db} \"SELECT * FROM players WHERE username='<user>'\"")
print("=" * 78)
PY
```

### 3. Reportar ao usuário

A saída do script já é o relatório final. Apresente o output integral e adicione 1 linha de síntese (ex: "3 jogadores: jhoumedeiros pronto pra relatório robusto, LucasCamilo10 só com daily — sem análise de tempo possível").

## Diretrizes

- Tom direto, PT-BR caveman (CLAUDE.md §Communication).
- Não inventar — só o que vier do DB.
- Não rodar análises pesadas; só leitura.
- Sem argumentos; lê tudo da base.

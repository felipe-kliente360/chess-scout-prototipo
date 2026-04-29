#!/usr/bin/env python3.12
"""Exporta o cache de posições como JSON para o browser consumir.

Output: data/openings/position_cache.json
Formato: { "<fen_key>": { "depth": N, "best_move": "...", "evaluation": "...", "mate": "..." } }
Mantém apenas a entry de MAIOR depth por fen_key (mais valiosa).

Roda antes de cada coleta no browser para o index.html ter o cache disponível.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "_chess_shared"))
from history import open_db  # noqa: E402

DB_PATH = ROOT / "data" / "history.db"
OUT = ROOT / "data" / "openings" / "position_cache.json"


def main():
    if not DB_PATH.is_file():
        raise SystemExit(f"❌ {DB_PATH} não existe — rode build_position_cache.py antes.")
    conn = open_db(DB_PATH)
    cur = conn.execute("""
      SELECT fen_key, depth, best_move, evaluation, mate
      FROM position_cache p1
      WHERE depth = (SELECT MAX(depth) FROM position_cache p2 WHERE p2.fen_key = p1.fen_key)
    """)
    cache = {}
    for row in cur.fetchall():
        cache[row["fen_key"]] = {
            "depth": row["depth"],
            "best_move": row["best_move"] or "",
            "evaluation": row["evaluation"] or "",
            "mate": row["mate"] or "",
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUT.stat().st_size // 1024
    print(f"✅ {OUT.relative_to(ROOT)}  ·  {len(cache)} posições  ·  {size_kb} KB")


if __name__ == "__main__":
    main()

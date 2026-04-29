#!/usr/bin/env python3.12
"""Importa novas posições de um analysis CSV recém-baixado para o cache SQLite.

Roda depois que você baixou o `<username>_<stamp>_analysis_d<N>.csv` do browser.
Idempotente — re-rodar não duplica.

Uso: python scripts/import_new_analysis.py <analysis.csv>
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "_chess_shared"))
from history import open_db, cache_position, cache_stats  # noqa: E402

DB_PATH = ROOT / "data" / "history.db"


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python scripts/import_new_analysis.py <analysis.csv>")
    csv_path = Path(sys.argv[1]).resolve()
    if not csv_path.is_file():
        raise SystemExit(f"❌ Não encontrado: {csv_path}")

    df = pd.read_csv(csv_path)
    if not {"fen_before", "depth", "best_move"}.issubset(df.columns):
        raise SystemExit("❌ CSV não tem colunas esperadas (fen_before, depth, best_move).")

    conn = open_db(DB_PATH)
    inserted = 0
    for _, r in df.iterrows():
        fen = str(r.get("fen_before") or "").strip()
        try:
            depth = int(r.get("depth"))
        except (TypeError, ValueError):
            continue
        if not fen or depth <= 0:
            continue
        cache_position(
            conn, fen, depth,
            best_move=str(r.get("best_move") or "").strip(),
            evaluation=str(r.get("evaluation") or "").strip(),
            mate=str(r.get("mate") or "").strip(),
            continuation=str(r.get("continuation") or "").strip(),
        )
        inserted += 1
    conn.commit()
    stats = cache_stats(conn)
    conn.close()
    print(f"✅ {csv_path.name}  ·  {inserted} entries inseridas/atualizadas.")
    print(f"   Cache total: {stats['n']} posições únicas (depth {stats['dmin']}–{stats['dmax']}).")


if __name__ == "__main__":
    main()

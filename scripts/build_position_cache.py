#!/usr/bin/env python3.12
"""Backfill do cache de posições a partir de TODOS os analysis CSVs já existentes em data/.

Roda uma vez (e quando quiser re-popular). Idempotente — mesma posição+depth substitui.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "_chess_shared"))
from history import open_db, cache_position, cache_stats  # noqa: E402

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "history.db"


def main():
    if not DATA_DIR.is_dir():
        raise SystemExit(f"❌ {DATA_DIR} não existe.")
    csvs = sorted(DATA_DIR.rglob("*_analysis_d*.csv"))
    if not csvs:
        raise SystemExit("❌ Nenhum analysis CSV encontrado em data/.")

    conn = open_db(DB_PATH)
    inserted = 0
    skipped = 0
    files_processed = 0

    for csv_path in csvs:
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            print(f"⚠ {csv_path.name}: {e}")
            continue
        if not {"fen_before", "depth", "best_move"}.issubset(df.columns):
            skipped += len(df) if len(df) else 0
            continue
        for _, r in df.iterrows():
            fen = str(r.get("fen_before") or "").strip()
            depth = r.get("depth")
            try:
                depth = int(depth)
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
        files_processed += 1
        if files_processed % 5 == 0:
            conn.commit()
            print(f"  … {files_processed}/{len(csvs)} arquivos · {inserted} posições gravadas")
    conn.commit()
    stats = cache_stats(conn)
    conn.close()
    print(f"✅ Backfill concluído: {inserted} entries inseridas/atualizadas a partir de {files_processed} CSVs.")
    print(f"   Cache atual: {stats['n']} posições únicas (depth {stats['dmin']}–{stats['dmax']}).")


if __name__ == "__main__":
    main()

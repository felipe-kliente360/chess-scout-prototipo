#!/usr/bin/env python3
"""Migração one-shot: importa CSVs arquivados em data/<user>/*_report/ para history.db.

Lê todos os pares games+analysis de cada subpasta de relatório arquivado e
popula games + game_analyses, idempotente (UPSERT). Útil pra não perder
dados históricos ao migrar do pipeline CSV → SQLite.

Uso:
    python scripts/import_csv_to_db.py [--user X]   # filtra por username
    python scripts/import_csv_to_db.py --dry-run    # só mostra o que faria
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SHARED = ROOT / ".claude" / "skills" / "_chess_shared"
sys.path.insert(0, str(SHARED))

from history import open_db, upsert_games_batch, save_analysis_batch  # type: ignore

DB_PATH = DATA / "history.db"


def find_pairs(user_filter: str | None):
    """Acha pares (games_csv, analysis_csv, username) em data/<user>/*_report/."""
    pairs = []
    for user_dir in DATA.iterdir():
        if not user_dir.is_dir() or user_dir.name.startswith("."):
            continue
        if user_filter and user_dir.name.lower() != user_filter.lower():
            continue
        for report_dir in user_dir.glob("*_report"):
            if not report_dir.is_dir():
                continue
            games_csv = next(iter(report_dir.glob(f"{user_dir.name}_*_games_*.csv")), None)
            analysis_csv = next(iter(report_dir.glob(f"{user_dir.name}_*_analysis_d*.csv")), None)
            if games_csv and analysis_csv:
                pairs.append((games_csv, analysis_csv, user_dir.name))
    return pairs


def import_pair(conn, games_csv: Path, analysis_csv: Path, username: str, dry: bool):
    games_df = pd.read_csv(games_csv)
    an_df = pd.read_csv(analysis_csv)

    depth_match = re.search(r"_d(\d+)(?:[_.])", analysis_csv.name)
    depth = int(depth_match.group(1)) if depth_match else 10

    # Monta lista de games
    games_records = []
    games_df["__index"] = range(1, len(games_df) + 1)
    for _, row in games_df.iterrows():
        gid = (row.get("url") or "").strip() or f"{username}_{row.get('date','')}_{row.get('opponent','')}"
        games_records.append({
            "game_id": gid, "username": username,
            "date": str(row.get("date") or ""),
            "color": str(row.get("color") or ""),
            "opponent": str(row.get("opponent") or ""),
            "opponent_rating": int(row["opponent_rating"]) if pd.notna(row.get("opponent_rating")) and str(row.get("opponent_rating")).strip() else None,
            "my_rating": int(row["my_rating"]) if pd.notna(row.get("my_rating")) and str(row.get("my_rating")).strip() else None,
            "result": str(row.get("result") or ""),
            "termination": str(row.get("termination") or ""),
            "time_control": str(row.get("time_control") or ""),
            "time_class": str(row.get("time_class") or ""),
            "opening": str(row.get("opening") or ""),
            "eco": str(row.get("eco") or ""),
            "eco_ply": int(row["eco_ply"]) if pd.notna(row.get("eco_ply")) and str(row.get("eco_ply")).strip() else None,
            "eco_family": str(row.get("eco_family") or ""),
            "url": str(row.get("url") or ""),
            "pgn": str(row.get("pgn") or ""),
        })
    idx_to_gid = {r["__index"]: g["game_id"] for r, g in zip(games_df.to_dict("records"), games_records)}

    # Monta lista de analyses
    analyses_records = []
    for _, row in an_df.iterrows():
        gi = row.get("game_index")
        gid = idx_to_gid.get(int(gi)) if pd.notna(gi) else None
        if not gid:
            continue
        analyses_records.append({
            "game_id": gid,
            "ply": int(row.get("ply") or 0),
            "side_to_move": str(row.get("side_to_move") or ""),
            "move_san": str(row.get("move_san") or ""),
            "move_uci": str(row.get("move_uci") or ""),
            "fen_before": str(row.get("fen_before") or ""),
            "depth": int(row.get("depth") or depth),
            "evaluation": str(row.get("evaluation")) if pd.notna(row.get("evaluation")) and str(row.get("evaluation")).strip() else None,
            "mate": str(row.get("mate")) if pd.notna(row.get("mate")) and str(row.get("mate")).strip() else None,
            "best_move": str(row.get("best_move") or "") or None,
            "continuation": str(row.get("continuation") or "") or None,
            "tactical_theme": str(row.get("tactical_theme") or "") or None,
            "tactical_confidence": float(row["tactical_confidence"]) if pd.notna(row.get("tactical_confidence")) and str(row.get("tactical_confidence")).strip() else None,
            "tactical_source": str(row.get("tactical_source") or "") or None,
        })

    print(f"  {games_csv.name}: {len(games_records)} jogos | {analysis_csv.name}: {len(analyses_records)} lances (depth {depth})")
    if dry:
        return 0, 0
    n_g = upsert_games_batch(conn, games_records)
    n_a = save_analysis_batch(conn, analyses_records)
    return n_g, n_a


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user", help="filtra um username")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pairs = find_pairs(args.user)
    if not pairs:
        raise SystemExit("nenhum par games+analysis encontrado em data/<user>/*_report/")
    print(f"📦 {len(pairs)} pares encontrados")
    conn = open_db(DB_PATH)
    total_g = total_a = 0
    for games_csv, analysis_csv, user in pairs:
        print(f"\n• {user}")
        ng, na = import_pair(conn, games_csv, analysis_csv, user, args.dry_run)
        total_g += ng; total_a += na
    conn.close()
    print(f"\n✅ {total_g} jogos | {total_a} lances importados.")


if __name__ == "__main__":
    main()

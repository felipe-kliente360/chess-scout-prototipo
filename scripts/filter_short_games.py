#!/usr/bin/env python3.12
"""Remove partidas com menos de N plies (default 15) do par games+analysis CSVs.

Mantém alinhamento entre os dois CSVs remapeando game_index após o filtro.
Renomeia os arquivos com a nova contagem (e remove os originais).

Uso: python scripts/filter_short_games.py <games.csv> <analysis.csv> [--min-plies 15]
"""
from __future__ import annotations

import argparse
import io
import re
from pathlib import Path

import chess
import chess.pgn
import pandas as pd


def count_plies(pgn: str) -> int:
    if not pgn or pd.isna(pgn):
        return 0
    game = chess.pgn.read_game(io.StringIO(str(pgn)))
    if game is None:
        return 0
    return sum(1 for _ in game.mainline_moves())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("games_csv", type=Path)
    ap.add_argument("analysis_csv", type=Path)
    ap.add_argument("--min-plies", type=int, default=15)
    args = ap.parse_args()

    games_path = args.games_csv.resolve()
    analysis_path = args.analysis_csv.resolve()
    if not games_path.is_file() or not analysis_path.is_file():
        raise SystemExit(f"❌ Arquivos não encontrados: {games_path} | {analysis_path}")

    games = pd.read_csv(games_path)
    analysis = pd.read_csv(analysis_path)
    n_in = len(games)

    games = games.reset_index(drop=True)
    games["_orig_index"] = games.index + 1
    games["_plies"] = games["pgn"].map(count_plies)

    keep = games[games["_plies"] >= args.min_plies].copy().reset_index(drop=True)
    n_out = len(keep)
    dropped = n_in - n_out
    if n_out == 0:
        raise SystemExit(f"❌ Nenhuma partida sobrou com >= {args.min_plies} plies.")

    keep["_new_index"] = keep.index + 1
    index_map = dict(zip(keep["_orig_index"], keep["_new_index"]))

    keep = keep.drop(columns=["_orig_index", "_plies", "_new_index"])

    if "game_index" not in analysis.columns:
        raise SystemExit("❌ analysis.csv sem coluna game_index.")
    analysis_keep = analysis[analysis["game_index"].isin(index_map)].copy()
    analysis_keep["game_index"] = analysis_keep["game_index"].map(index_map)
    analysis_keep = analysis_keep.sort_values(["game_index", "ply"]).reset_index(drop=True)

    new_games_name = re.sub(r"_games_\d+\.csv$", f"_games_{n_out}.csv", games_path.name)
    new_games_path = games_path.parent / new_games_name
    new_analysis_path = analysis_path  # mesmo nome (depth fica)

    keep.to_csv(new_games_path, index=False)
    analysis_keep.to_csv(new_analysis_path, index=False)

    if new_games_path != games_path:
        games_path.unlink()

    print(f"✅ Filtro aplicado (mínimo {args.min_plies} plies):")
    print(f"   games:    {n_in} → {n_out}  ({dropped} descartadas)")
    print(f"   analysis: {len(analysis)} → {len(analysis_keep)} posições")
    print(f"   →         {new_games_path.name}")
    print(f"   →         {new_analysis_path.name}")


if __name__ == "__main__":
    main()

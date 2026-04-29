#!/usr/bin/env python3.12
"""Enriquece um CSV de partidas com classificação ECO (Lichess), in-place.

Adiciona/atualiza colunas: eco, opening, eco_ply, eco_family.
Usa data/openings/eco.json (índice EPD → {eco, name, ply}).

Uso: python scripts/enrich_eco.py <caminho_para_games.csv>
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import chess
import chess.pgn
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ECO_INDEX = ROOT / "data" / "openings" / "eco.json"
ECO_MAX_PLIES = 25


def fen_to_epd(fen: str) -> str:
    return " ".join(fen.split(" ")[:3])


def classify(pgn: str, index: dict) -> dict | None:
    if not pgn or pd.isna(pgn):
        return None
    game = chess.pgn.read_game(io.StringIO(str(pgn)))
    if game is None:
        return None
    board = game.board()
    best = None
    for i, mv in enumerate(game.mainline_moves()):
        if i >= ECO_MAX_PLIES:
            break
        board.push(mv)
        epd = fen_to_epd(board.fen())
        hit = index.get(epd)
        if hit:
            best = {**hit, "eco_ply": i + 1}
    return best


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python scripts/enrich_eco.py <games.csv>")
    csv_path = Path(sys.argv[1]).resolve()
    if not csv_path.is_file():
        raise SystemExit(f"❌ CSV não encontrado: {csv_path}")
    if not ECO_INDEX.is_file():
        raise SystemExit(f"❌ Índice ECO não encontrado em {ECO_INDEX}. Rode scripts/build_eco_index.py.")

    index = json.loads(ECO_INDEX.read_text(encoding="utf-8"))
    df = pd.read_csv(csv_path)
    if "pgn" not in df.columns:
        raise SystemExit("❌ CSV não tem coluna 'pgn'.")

    eco_col, opening_col, ply_col, family_col = [], [], [], []
    hits = 0
    for pgn in df["pgn"]:
        cls = classify(pgn, index)
        if cls:
            eco_col.append(cls["eco"])
            opening_col.append(f"{cls['eco']} {cls['name']}")
            ply_col.append(cls["eco_ply"])
            family_col.append(cls["name"].split(":")[0].strip())
            hits += 1
        else:
            eco_col.append("")
            opening_col.append("")
            ply_col.append("")
            family_col.append("")

    df["eco"] = eco_col
    df["opening"] = opening_col
    df["eco_ply"] = ply_col
    df["eco_family"] = family_col

    df.to_csv(csv_path, index=False)
    pct = round(100 * hits / len(df), 1) if len(df) else 0
    print(f"✅ {csv_path.name}  ·  {hits}/{len(df)} classificadas ({pct}%)")


if __name__ == "__main__":
    main()

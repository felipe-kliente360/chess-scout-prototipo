#!/usr/bin/env python3.12
"""Consolida a/b/c/d/e.tsv (Lichess) em data/openings/eco.json indexado por EPD."""

import csv, json, sys
from pathlib import Path
import chess, chess.pgn
import io

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "openings"
OUT = SRC / "eco.json"

def epd_after(pgn_moves: str) -> str | None:
    game = chess.pgn.read_game(io.StringIO(pgn_moves))
    if game is None:
        return None
    board = game.board()
    for mv in game.mainline_moves():
        board.push(mv)
    parts = board.fen().split(" ")
    return " ".join(parts[:3])

def main():
    index: dict[str, dict] = {}
    collisions = 0
    for letter in "abcde":
        path = SRC / f"{letter}.tsv"
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                eco, name, pgn = row["eco"], row["name"], row["pgn"]
                epd = epd_after(pgn)
                if not epd:
                    continue
                ply = len(pgn.replace(".", " ").split()) - len([t for t in pgn.split() if t.endswith(".")])
                entry = {"eco": eco, "name": name, "ply": ply}
                if epd in index:
                    if index[epd]["ply"] < ply:
                        index[epd] = entry
                    collisions += 1
                else:
                    index[epd] = entry
    OUT.write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    size_kb = OUT.stat().st_size // 1024
    print(f"✅ {OUT.relative_to(ROOT)}  ·  {len(index)} EPDs  ·  {collisions} colisões resolvidas  ·  {size_kb} KB")

if __name__ == "__main__":
    main()

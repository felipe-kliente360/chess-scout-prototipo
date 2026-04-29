#!/usr/bin/env python3
"""Build tactical themes index from woodpecker-puzzles release.

Lê arquivos puzzles_*.json.gz baixados do release e gera
data/tactical/themes_index.json indexando dois fingerprints:

  B = grafo posicional (relações entre peças R/D/T/B/N) — usado quando o
      app só tem o FEN e quer classificar a posição.
  C = delta após o best_move (que ataques novos surgem, captura, xeque) —
      usado quando o app tem FEN + best_move (Stockfish flagrou erro).

Cada fingerprint mapeia para os temas Lichess agregados, com top-3 temas e
contagens. Aplica stoplist de tags genéricas. Drop entries com n < min_count.

Uso:
  python scripts/build_tactical_index.py \\
    --source /tmp/woodpecker-data \\
    --out data/tactical/themes_index.json \\
    --min-count 3
"""
from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import chess

# Tags Lichess que não dizem nada sobre o motivo tático em si.
# Devem ser descartadas do agregado para não dominar o ranking.
STOPLIST = {
    # tags de fase / tamanho do puzzle (ruído quando agregado por padrão)
    "middlegame", "endgame", "opening",
    "short", "long", "veryLong", "oneMove",
    "advantage", "crushing", "equality",
    "master", "masterVsMaster", "superGM",
    "rookEndgame", "pawnEndgame", "queenEndgame", "knightEndgame",
    "bishopEndgame", "queenRookEndgame",
    "mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5",
    # tags descritivas mas não diagnósticas — não dizem o motivo tático
    "quietMove", "advancedPawn", "defensiveMove",
}

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
HIGH_VALUE = {chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN, chess.KING}
SYM = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
       chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}


def king_safety_tag(board: chess.Board, color: chess.Color) -> str:
    """ks_N (kingside, N atacantes próximos), qs_N, mid_N, unsafe_N."""
    king_sq = board.king(color)
    if king_sq is None:
        return "noking"
    f = chess.square_file(king_sq)
    if f >= 5:
        side = "ks"
    elif f <= 2:
        side = "qs"
    else:
        side = "mid"
    enemy = not color
    n_atk = 0
    for sq in chess.SQUARES:
        if chess.square_distance(sq, king_sq) <= 1 and sq != king_sq:
            if board.is_attacked_by(enemy, sq):
                n_atk += 1
    return f"{side}_{n_atk}"


def high_value_attacks(board: chess.Board, attacker_color: chess.Color):
    """Lista de tuplas (atacante_sym, alvo_sym, n_defensores) ordenadas por
    valor do alvo. Só conta alvos R/D/T/B/N (peões só se desprotegidos)."""
    attacks = []
    enemy = not attacker_color
    for sq in chess.SQUARES:
        target = board.piece_at(sq)
        if not target or target.color != enemy:
            continue
        if target.piece_type not in HIGH_VALUE:
            continue
        attackers = board.attackers(attacker_color, sq)
        if not attackers:
            continue
        defenders = board.attackers(enemy, sq)
        n_def = len(defenders)
        for atk_sq in attackers:
            atk_piece = board.piece_at(atk_sq)
            if not atk_piece:
                continue
            attacks.append((SYM[atk_piece.piece_type], SYM[target.piece_type],
                            n_def, PIECE_VALUES[target.piece_type]))
    attacks.sort(key=lambda t: (-t[3], t[0], t[1]))
    return attacks[:4]


def undefended_high_value(board: chess.Board, color: chess.Color):
    """Peças color sem defensor próprio (só R/D/T/B/N)."""
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.color != color:
            continue
        if p.piece_type not in HIGH_VALUE:
            continue
        if not board.attackers(color, sq):
            out.append((SYM[p.piece_type], PIECE_VALUES[p.piece_type]))
    out.sort(key=lambda t: (-t[1], t[0]))
    return [s for s, _ in out[:4]]


def open_files_near_king(board: chess.Board, target_color: chess.Color) -> int:
    """Colunas abertas/semi-abertas a ≤2 da coluna do rei target_color."""
    king_sq = board.king(target_color)
    if king_sq is None:
        return 0
    king_file = chess.square_file(king_sq)
    files_w = [0] * 8
    files_b = [0] * 8
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN:
            f = chess.square_file(sq)
            if p.color == chess.WHITE:
                files_w[f] += 1
            else:
                files_b[f] += 1
    n = 0
    for f in range(max(0, king_file - 2), min(8, king_file + 3)):
        if files_w[f] == 0 or files_b[f] == 0:
            n += 1
    return n


def fingerprint_b(board: chess.Board) -> str:
    """Hash B da posição (do ponto de vista do lado a mover = solver)."""
    stm = "w" if board.turn else "b"
    solver = board.turn
    enemy = not solver
    ks = king_safety_tag(board, solver)
    enemy_ks = king_safety_tag(board, enemy)
    atks = high_value_attacks(board, solver)
    atk_str = ";".join(f"{a}>{t}_d{d}" for a, t, d, _ in atks)
    undef = undefended_high_value(board, enemy)
    undef_str = ";".join(undef)
    open_f = open_files_near_king(board, enemy)
    return f"{stm}|sk_{ks}|ek_{enemy_ks}|{atk_str}|U:{undef_str}|of_{open_f}"


def fingerprint_c(board: chess.Board, best_move: chess.Move) -> str:
    """Hash C: delta provocado por best_move (do ponto de vista do solver).
    Captura o que best_move passa a atacar/ameaçar que não atacava antes.
    """
    solver = board.turn
    enemy = not solver

    pre_attacks = set()
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.color != enemy:
            continue
        if p.piece_type not in HIGH_VALUE:
            continue
        for atk_sq in board.attackers(solver, sq):
            atk = board.piece_at(atk_sq)
            if atk:
                pre_attacks.add((SYM[atk.piece_type], SYM[p.piece_type], sq))

    captured = ""
    cap_target = board.piece_at(best_move.to_square)
    if cap_target and cap_target.color == enemy:
        captured = SYM[cap_target.piece_type]

    after = board.copy(stack=False)
    after.push(best_move)
    is_check = after.is_check()
    is_mate = after.is_checkmate()

    post_attacks = set()
    for sq in chess.SQUARES:
        p = after.piece_at(sq)
        if not p or p.color != enemy:
            continue
        if p.piece_type not in HIGH_VALUE:
            continue
        for atk_sq in after.attackers(solver, sq):
            atk = after.piece_at(atk_sq)
            if atk:
                post_attacks.add((SYM[atk.piece_type], SYM[p.piece_type], sq))

    gained = post_attacks - pre_attacks
    gained_compact = sorted({(a, t) for a, t, _ in gained})
    n_targets = len({t for _, t in gained_compact})
    gain_str = ",".join(f"{a}>{t}" for a, t in gained_compact[:5])

    target_undef_after = 0
    for a, t, sq in gained:
        if not after.attackers(enemy, sq):
            target_undef_after = 1
            break

    return (f"g:{gain_str}|nT:{n_targets}|cap:{captured}"
            f"|chk:{int(is_check)}|mate:{int(is_mate)}|tU:{target_undef_after}")


def process_puzzle(p: dict) -> tuple[str | None, str | None, list[str]]:
    """Retorna (fp_b, fp_c, themes_filtered) ou (None, None, []) se inválido."""
    try:
        board = chess.Board(p["fen"])
        moves = p["lances"]
        if len(moves) < 2:
            return None, None, []
        # lances[0] é o lance do oponente que cria a posição-tarefa.
        board.push(chess.Move.from_uci(moves[0]))
        best = chess.Move.from_uci(moves[1])
        themes = [t for t in p.get("temas", []) if t and t not in STOPLIST]
        if not themes:
            return None, None, []
        fp_b = fingerprint_b(board)
        fp_c = fingerprint_c(board, best)
        return fp_b, fp_c, themes
    except Exception:
        return None, None, []


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True,
                    help="diretório com puzzles_*.json.gz baixados do release")
    ap.add_argument("--out", required=True,
                    help="caminho do JSON de saída (ex: data/tactical/themes_index.json)")
    ap.add_argument("--min-count", type=int, default=3,
                    help="descarta entradas com n < min_count (default 3)")
    ap.add_argument("--limit", type=int, default=0,
                    help="processa só os N primeiros de cada arquivo (debug)")
    args = ap.parse_args()

    src = Path(args.source).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(src.glob("puzzles_*.json.gz"))
    if not files:
        raise SystemExit(f"❌ nenhum puzzles_*.json.gz em {src}")

    counters_b: dict[str, Counter] = defaultdict(Counter)
    counters_c: dict[str, Counter] = defaultdict(Counter)
    n_total = n_kept = 0

    for fp in files:
        with gzip.open(fp, "rt") as fh:
            puzzles = json.load(fh)
        if args.limit:
            puzzles = puzzles[:args.limit]
        kept = 0
        for p in puzzles:
            n_total += 1
            fp_b, fp_c, themes = process_puzzle(p)
            if not themes:
                continue
            kept += 1
            n_kept += 1
            for t in themes:
                counters_b[fp_b][t] += 1
                counters_c[fp_c][t] += 1
        print(f"  {fp.name}: {kept}/{len(puzzles)} úteis")

    def consolidate(counters: dict[str, Counter]) -> dict:
        out = {}
        for fp, cnt in counters.items():
            n = sum(cnt.values())
            if n < args.min_count:
                continue
            top = cnt.most_common(3)
            out[fp] = {
                "t": [t for t, _ in top],
                "c": [c for _, c in top],
                "n": n,
            }
        return out

    b_index = consolidate(counters_b)
    c_index = consolidate(counters_c)

    payload = {
        "version": 1,
        "built_at": date.today().isoformat(),
        "fingerprint_version": "B1+C1",
        "source_repo": "felipe-kliente360/woodpecker-puzzles",
        "n_puzzles_seen": n_total,
        "n_puzzles_indexed": n_kept,
        "min_count": args.min_count,
        "stoplist_themes": sorted(STOPLIST),
        "B": b_index,
        "C": c_index,
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"\n✅ {out_path}")
    print(f"   B: {len(b_index)} fingerprints | C: {len(c_index)} fingerprints")
    print(f"   {n_kept}/{n_total} puzzles indexados | tamanho: {size_kb:.1f} KB")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Lê os CSVs mais recentes de partidas + análise Stockfish do jogador
e produz um JSON com todas as métricas necessárias para o relatório.

Uso: python compute.py <username>
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import chess

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data"

DATE_RE = re.compile(r"(\d{8}T\d{6}|\d{4}-\d{2}-\d{2})")
MATE_CAP_PAWNS = 10.0
LOSS_CAP_CP = 1000


def find_latest_csvs(username: str) -> tuple[Path, Path, str]:
    """CSVs sempre vivem em data/ (raiz). A pasta por user é criada só ao gerar o relatório."""
    games = sorted(
        list(DATA_DIR.glob(f"{username}_*_games_*.csv"))
        + list(DATA_DIR.glob(f"{username}_games_*.csv")),
        key=lambda p: p.stat().st_mtime,
    )
    analyses = sorted(
        list(DATA_DIR.glob(f"{username}_*_analysis_d*.csv"))
        + list(DATA_DIR.glob(f"{username}_analysis_d*_*.csv")),
        key=lambda p: p.stat().st_mtime,
    )
    if not games or not analyses:
        raise SystemExit(
            f"❌ CSVs não encontrados em {DATA_DIR}. "
            f"Esperado: {username}_<timestamp>_games_<N>.csv e {username}_<timestamp>_analysis_d<N>.csv "
            f"(coloque-os diretamente em data/)"
        )
    games_path = games[-1]
    analysis_path = analyses[-1]
    stamp_match = DATE_RE.search(analysis_path.name) or DATE_RE.search(games_path.name)
    stamp = stamp_match.group(1) if stamp_match else date.today().strftime("%Y%m%dT%H%M%S")
    return games_path, analysis_path, stamp


def detect_position_features(fen: str) -> list[str]:
    """Detecta padrões estruturais canônicos numa posição (FEN).
    Retorna lista de tags como 'IQP-white', 'opposite-castle', 'open-c-file',
    'closed-center', 'fianchetto-kingside', etc. Vocabulário ancorado em
    Soltis (Pawn Structure Chess) e Kmoch (Pawn Power in Chess).

    Tags possíveis (ver theory.md §20):
      IQP-{white|black}, hanging-pawns-{white|black}, backward-pawn-{white|black}
      closed-center, semi-open-center, open-center
      same-side-castle, opposite-castle, uncastled-king
      fianchetto-kingside-{white|black}, fianchetto-queenside-{white|black}
      open-{a..h}-file, semi-open-{a..h}-file
      bishop-pair-{white|black}
      pawn-majority-queenside-{white|black}, pawn-majority-kingside-{white|black}
    """
    try:
        board = chess.Board(fen)
    except Exception:
        return []
    tags = []

    # Helper: peões por cor e por arquivo
    files_white = [0] * 8  # contagem por arquivo (a=0..h=7)
    files_black = [0] * 8
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN:
            f = chess.square_file(sq)
            if p.color == chess.WHITE:
                files_white[f] += 1
            else:
                files_black[f] += 1

    # Helper: posição do rei (para detectar roque)
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)

    # ── IQP (peão dama isolado) ─────────────────────────────────
    # Branco: peão em d4 sem peões em c e e (só peão d isolado)
    if files_white[3] >= 1 and files_white[2] == 0 and files_white[4] == 0:
        # Só conta como IQP se o peão d está realmente em d4 (estrutura central)
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.piece_type == chess.PAWN and p.color == chess.WHITE and chess.square_file(sq) == 3:
                if chess.square_rank(sq) == 3:  # d4
                    tags.append("IQP-white")
                    break
    if files_black[3] >= 1 and files_black[2] == 0 and files_black[4] == 0:
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.piece_type == chess.PAWN and p.color == chess.BLACK and chess.square_file(sq) == 3:
                if chess.square_rank(sq) == 4:  # d5
                    tags.append("IQP-black")
                    break

    # ── Peões pendurados (hanging pawns: c+d ou d+e juntos sem suporte) ──
    # Branco: peões c4+d4 (ou d4+e4), sem b ou e (ou d+e sem c+f)
    if files_white[2] == 1 and files_white[3] == 1 and files_white[1] == 0 and files_white[4] == 0:
        tags.append("hanging-pawns-white")
    if files_black[2] == 1 and files_black[3] == 1 and files_black[1] == 0 and files_black[4] == 0:
        tags.append("hanging-pawns-black")

    # ── Roque (cor dos reis) ────────────────────────────────────
    def castle_side(king_sq):
        if king_sq is None:
            return None
        f = chess.square_file(king_sq)
        if f >= 5:
            return "kingside"
        if f <= 2:
            return "queenside"
        return "center"
    wcs = castle_side(wk)
    bcs = castle_side(bk)
    if wcs == "center" and bcs == "center":
        tags.append("uncastled-king")
    elif wcs and bcs and wcs != "center" and bcs != "center":
        if wcs == bcs:
            tags.append("same-side-castle")
        else:
            tags.append("opposite-castle")

    # ── Fianchetto (bispo em b2/g2 com peão em b3/g3 ou b7/g7) ──
    def has_fianchetto(color, side):
        if color == chess.WHITE:
            bishop_sq = chess.G2 if side == "kingside" else chess.B2
            pawn_sq = chess.G3 if side == "kingside" else chess.B3
        else:
            bishop_sq = chess.G7 if side == "kingside" else chess.B7
            pawn_sq = chess.G6 if side == "kingside" else chess.B6
        bp = board.piece_at(bishop_sq)
        pp = board.piece_at(pawn_sq)
        return (bp and bp.piece_type == chess.BISHOP and bp.color == color and
                pp and pp.piece_type == chess.PAWN and pp.color == color)
    for color, label in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        for side in ("kingside", "queenside"):
            if has_fianchetto(color, side):
                tags.append(f"fianchetto-{side}-{label}")

    # ── Centro (caráter aberto / fechado / semi-aberto) ────────
    # Conta peões nas 4 casas centrais (d4,d5,e4,e5) e adjacentes
    central_pawns = 0
    for sq in (chess.D4, chess.D5, chess.E4, chess.E5):
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN:
            central_pawns += 1
    # Peões locked: d4 vs d5 ou e4 vs e5 trancados
    locked = False
    for f, rank_white, rank_black in [(3, 3, 4), (4, 3, 4)]:  # d-file, e-file
        wp = board.piece_at(chess.square(f, rank_white))
        bp = board.piece_at(chess.square(f, rank_black))
        if (wp and wp.piece_type == chess.PAWN and wp.color == chess.WHITE and
                bp and bp.piece_type == chess.PAWN and bp.color == chess.BLACK):
            locked = True
            break
    if locked:
        tags.append("closed-center")
    elif central_pawns == 0:
        tags.append("open-center")
    elif central_pawns <= 2:
        tags.append("semi-open-center")

    # ── Colunas abertas / semi-abertas ─────────────────────────
    file_letters = "abcdefgh"
    for f in range(8):
        if files_white[f] == 0 and files_black[f] == 0:
            tags.append(f"open-{file_letters[f]}-file")
        elif files_white[f] == 0 or files_black[f] == 0:
            # Semi-aberta só vale a pena destacar para colunas centrais ou semi-centrais
            if f in (2, 3, 4, 5):
                tags.append(f"semi-open-{file_letters[f]}-file")

    # ── Par de bispos ──────────────────────────────────────────
    for color, label in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        bishops = [sq for sq in chess.SQUARES
                   if (p := board.piece_at(sq)) and p.piece_type == chess.BISHOP and p.color == color]
        if len(bishops) == 2:
            # Par real só se forem de cores opostas
            colors = {chess.square_rank(b) + chess.square_file(b) for b in bishops}
            if len(colors) == 2:
                tags.append(f"bishop-pair-{label}")

    # ── Maioria de peões (queenside vs kingside) ────────────────
    # Detecta apenas se houver assimetria clara (≥2 peões a mais de um lado)
    qs_white = sum(files_white[:4])
    ks_white = sum(files_white[4:])
    qs_black = sum(files_black[:4])
    ks_black = sum(files_black[4:])
    if qs_white - qs_black >= 2:
        tags.append("pawn-majority-queenside-white")
    elif qs_black - qs_white >= 2:
        tags.append("pawn-majority-queenside-black")
    if ks_white - ks_black >= 2:
        tags.append("pawn-majority-kingside-white")
    elif ks_black - ks_white >= 2:
        tags.append("pawn-majority-kingside-black")

    return tags


def cp_from_row(row) -> float:
    """Eval em centipeões (perspectiva das brancas). Mate vira ±MATE_CAP."""
    mate = row.get("mate")
    try:
        if mate not in (None, "", "nan") and not pd.isna(mate):
            mate_v = float(mate)
            return MATE_CAP_PAWNS * 100 * (1 if mate_v > 0 else -1)
    except (ValueError, TypeError):
        pass
    ev = row.get("evaluation")
    try:
        return float(ev) * 100
    except (ValueError, TypeError):
        return 0.0


def classify_loss(cp: float) -> str:
    if cp >= 300:
        return "blunder"
    if cp >= 100:
        return "mistake"
    if cp >= 50:
        return "inaccuracy"
    return "good"


def phase_of_ply(ply: int, total_plies: int) -> str:
    if ply <= 20:
        return "abertura"
    if total_plies and ply >= total_plies - 20:
        return "final"
    return "meio-jogo"


def compute_accuracy(acpl: float) -> float:
    """Aproximação tipo chess.com: 100 * exp(-0.005 * acpl). Faixa 0-100."""
    import math
    if acpl < 0:
        acpl = 0
    return round(100 * math.exp(-0.005 * acpl), 2)


def expected_acpl(rating: float | int) -> float:
    """ACPL típico esperado para um rating (referência depth=20).
    Empírico: 130 * exp(-rating/1200). Saturação inferior em 8 cp (limite GM)."""
    import math
    if rating is None or rating <= 0:
        rating = 1200  # padrão amador médio
    return max(8.0, 130.0 * math.exp(-float(rating) / 1200.0))


_DEPTH_ANCHORS = [(10, 0.50), (12, 0.55), (15, 0.65), (18, 0.85),
                  (20, 1.00), (22, 1.08), (25, 1.15)]


def depth_factor(depth: int | None) -> float:
    """Fator multiplicativo: ACPL_d20_eq = ACPL_medido / depth_factor(depth_real).
    Interpolação linear entre âncoras empíricas."""
    if depth is None:
        return 1.0
    if depth <= _DEPTH_ANCHORS[0][0]:
        return _DEPTH_ANCHORS[0][1]
    if depth >= _DEPTH_ANCHORS[-1][0]:
        return _DEPTH_ANCHORS[-1][1]
    for (d1, v1), (d2, v2) in zip(_DEPTH_ANCHORS, _DEPTH_ANCHORS[1:]):
        if d1 <= depth <= d2:
            return v1 + (v2 - v1) * (depth - d1) / (d2 - d1)
    return 1.0


def compute_score10(acpl, depth=None, rating=None):
    """Score 0-10 calibrado por depth e rating.

    Lógica: normaliza ACPL para o equivalente a depth 20, compara com o ACPL esperado
    para o rating do jogador, e mapeia o ratio para um score onde:
      - ratio 0.0 (perfeito)              → 10
      - ratio 0.5 (2x melhor que esperado) → 7.8
      - ratio 1.0 (dentro do esperado)    → 6.1
      - ratio 2.0 (2x pior que esperado)  → 3.7
      - ratio 3.0+                        → < 2.5

    Score 6 é o baseline "joguei como esperado para meu rating".
    """
    import math
    if acpl is None or acpl < 0:
        return 0.0
    df = depth_factor(depth) if depth is not None else 1.0
    acpl_eq = float(acpl) / df if df > 0 else float(acpl)
    expected = expected_acpl(rating)
    ratio = acpl_eq / expected if expected > 0 else 0
    return round(10 * math.exp(-ratio / 2), 1)


def compute_confidence_pct(n_games: int, depth: int | None, eco_coverage: float) -> int:
    """Índice 0-100% de relevância estatística.
    Pesos: 50% amostra (satura em 50 jogos) + 30% depth (satura em 18) + 20% cobertura ECO."""
    sample_w = min(n_games / 50, 1.0)
    depth_w = min((depth or 0) / 18, 1.0)
    eco_w = min((eco_coverage or 0) / 100, 1.0)
    return round(100 * (0.5 * sample_w + 0.3 * depth_w + 0.2 * eco_w))


CANONICAL_THEMES = {
    "fork": "garfo — uma peça ataca duas ao mesmo tempo",
    "pin": "cravada — peça presa que não pode mover sem expor outra",
    "skewer": "espeto — força a peça da frente a sair, capturando a de trás",
    "discovered_attack": "ataque descoberto — uma peça sai e revela ataque de outra",
    "double_attack": "ataque duplo — duas ameaças simultâneas",
    "deflection": "desvio — força peça defensora a sair de função",
    "decoy": "isca — atrai peça para casa ruim",
    "removing_defender": "remoção do defensor — captura ou afasta quem protege",
    "back_rank": "fila do fundo — mate na 1ª/8ª linha por rei sem fuga",
    "smothered_mate": "mate sufocado — cavalo dá mate com peças próprias bloqueando o rei",
    "double_check": "xeque duplo — duas peças dão xeque, rei obrigado a mover",
    "mate_in_2": "mate em 2 — sequência forçada",
    "mate_in_3": "mate em 3",
    "sacrifice": "sacrifício — entregar material por vantagem maior",
    "zwischenzug": "lance intermediário — joga forçante antes do esperado",
    "zugzwang": "obrigação de jogar — qualquer lance piora a posição",
    "rook_endgame": "final de torres — Lucena, Philidor, atividade da torre",
    "pawn_endgame": "final de peões — oposição, regra do quadrado",
    "opposite_color_bishops": "bispos de cores opostas — frequente empate",
    "opening_trap": "armadilha de abertura — explora erros típicos das primeiras jogadas",
    "attack_on_king": "ataque ao rei — sacrifícios em h7/g7, abrir colunas",
    "defensive_move": "lance defensivo — encontrar único movimento que salva",
}


def derive_puzzle_program(games_df, by_phase, kpis, head_to_head, time_classes):
    """Sugere rating de puzzles + temas táticos a treinar.
    Estrutura consumível por um app externo de treino tático."""
    rating_basis = None
    rating_value = None
    if "my_rating" in games_df.columns:
        my_ratings = pd.to_numeric(games_df["my_rating"], errors="coerce").dropna()
        if len(my_ratings):
            rating_value = int(round(my_ratings.mean()))
            rating_basis = f"média de my_rating em {len(my_ratings)} partidas"
    if rating_value is None:
        opp_ratings = [h["avg_opp_rating"] for h in head_to_head if h.get("avg_opp_rating")]
        if opp_ratings:
            rating_value = int(round(sum(opp_ratings) / len(opp_ratings)))
            rating_basis = f"média de rating de adversários (proxy) — {len(opp_ratings)} oponentes"
    if rating_value is None:
        rating_value = 1200
        rating_basis = "padrão (sem dados de rating)"

    rating_lo = max(400, rating_value - 100)
    rating_hi = min(2800, rating_value + 100)

    themes = []
    total_errs = max(1, kpis.get("blunders", 0) + kpis.get("mistakes", 0))
    final_errs = by_phase["final"]["blunders"] + by_phase["final"]["mistakes"]
    open_errs = by_phase["abertura"]["blunders"] + by_phase["abertura"]["mistakes"]
    mid_errs = by_phase["meio-jogo"]["blunders"] + by_phase["meio-jogo"]["mistakes"]

    if final_errs / total_errs >= 0.4:
        themes += [
            {"theme": "rook_endgame", "priority": "alta",
             "rationale": f"{final_errs}/{total_errs} erros graves+médios estão no final"},
            {"theme": "pawn_endgame", "priority": "média",
             "rationale": "completa o reforço técnico de finais"},
        ]
    if open_errs / total_errs >= 0.3:
        themes.append({"theme": "opening_trap", "priority": "alta",
                       "rationale": f"{open_errs} erros graves+médios na abertura"})
    if mid_errs / total_errs >= 0.4:
        themes.append({"theme": "double_attack", "priority": "alta",
                       "rationale": f"{mid_errs} erros no meio-jogo — falha em ver ameaças simultâneas"})

    if rating_value < 1000:
        themes += [
            {"theme": "fork", "priority": "alta", "rationale": "fundamento tático básico < 1000"},
            {"theme": "pin", "priority": "alta", "rationale": "fundamento tático básico"},
            {"theme": "back_rank", "priority": "média", "rationale": "padrão de mate frequente nessa faixa"},
        ]
    elif rating_value < 1400:
        themes += [
            {"theme": "discovered_attack", "priority": "alta", "rationale": "padrão típico de evolução 1000-1400"},
            {"theme": "deflection", "priority": "média", "rationale": "começa a aparecer em puzzles dessa faixa"},
            {"theme": "back_rank", "priority": "média", "rationale": "mate ainda frequente"},
        ]
    elif rating_value < 1800:
        themes += [
            {"theme": "removing_defender", "priority": "alta", "rationale": "tema central da faixa 1400-1800"},
            {"theme": "skewer", "priority": "média", "rationale": "padrão refinado, mais raro mas decisivo"},
            {"theme": "attack_on_king", "priority": "média", "rationale": "ataques temáticos começam a aparecer"},
        ]
    else:
        themes += [
            {"theme": "zwischenzug", "priority": "alta", "rationale": "tema avançado, decisivo em jogo de qualidade"},
            {"theme": "zugzwang", "priority": "média", "rationale": "essencial em finais de alto nível"},
            {"theme": "sacrifice", "priority": "média", "rationale": "cálculo profundo de compensação"},
        ]

    if "bullet" in (time_classes or []):
        themes.append({"theme": "mate_in_2", "priority": "média",
                       "rationale": "reflexo em padrões curtos compensa pressão de tempo"})

    seen = set()
    unique_themes = []
    for t in themes:
        if t["theme"] in seen:
            continue
        seen.add(t["theme"])
        t["label"] = CANONICAL_THEMES.get(t["theme"], t["theme"])
        unique_themes.append(t)

    return {
        "suggested_rating": rating_value,
        "rating_range": [rating_lo, rating_hi],
        "rating_basis": rating_basis,
        "themes": unique_themes[:8],
    }


def safe_int(v, default=0):
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def load_previous_computed(username: str, current_stamp: str):
    """Procura computed JSONs em data/ (raiz, ciclo atual) e em data/<user>/*_report/ (anteriores arquivados)."""
    user_dir = DATA_DIR / username
    files = sorted(
        list(DATA_DIR.glob(f"{username}_*_computed.json"))
        + list(DATA_DIR.glob(f"{username}_computed_*.json"))
        + (list(user_dir.rglob(f"{username}_*_computed.json")) if user_dir.is_dir() else [])
        + (list(user_dir.rglob(f"{username}_computed_*.json")) if user_dir.is_dir() else []),
        key=lambda p: p.stat().st_mtime,
    )
    files = [f for f in files if current_stamp not in f.name]
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except Exception:
        return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python compute.py <username>")
    username = sys.argv[1].strip()
    if not DATA_DIR.is_dir():
        raise SystemExit(f"❌ Pasta de dados não encontrada: {DATA_DIR}")

    games_path, analysis_path, stamp = find_latest_csvs(username)
    print(f"📁 games:    {games_path.name}")
    print(f"📁 analysis: {analysis_path.name}")

    games_df = pd.read_csv(games_path)
    an_df = pd.read_csv(analysis_path)

    depth_match = re.search(r"_d(\d+)(?:[_.])", analysis_path.name)
    depth = int(depth_match.group(1)) if depth_match else None

    n_games = len(games_df)
    n_positions = len(an_df)

    games_df["index"] = range(1, n_games + 1)
    games_lookup = {row["index"]: row.to_dict() for _, row in games_df.iterrows()}

    # Rating do jogador (referência única para todo o cálculo de score):
    # prefere média de my_rating; cai para média de avg_opp_rating; default 1200.
    player_rating = None
    rating_basis = "padrão (sem dados)"
    if "my_rating" in games_df.columns:
        my_r = pd.to_numeric(games_df["my_rating"], errors="coerce").dropna()
        if len(my_r):
            player_rating = int(round(my_r.mean()))
            rating_basis = f"média de my_rating em {len(my_r)} partidas"
    if player_rating is None and "opponent_rating" in games_df.columns:
        opp_r = pd.to_numeric(games_df["opponent_rating"], errors="coerce").dropna()
        if len(opp_r):
            player_rating = int(round(opp_r.mean()))
            rating_basis = f"média de rating de adversários (proxy) — {len(opp_r)} partidas"
    if player_rating is None:
        player_rating = 1200

    an_df["cp"] = an_df.apply(cp_from_row, axis=1)
    an_df = an_df.sort_values(["game_index", "ply"]).reset_index(drop=True)

    move_records = []
    for game_idx, group in an_df.groupby("game_index"):
        group = group.sort_values("ply").reset_index(drop=True)
        total_plies = len(group)
        cps = group["cp"].tolist()
        sides = group["side_to_move"].tolist()
        sans = group["move_san"].tolist()
        bests = group.get("best_move", pd.Series([""] * total_plies)).tolist()
        plies = group["ply"].tolist()
        fens = group["fen_before"].tolist()

        for i in range(total_plies):
            cp_before = cps[i]
            cp_after = cps[i + 1] if i + 1 < total_plies else cp_before
            mover = sides[i]
            if mover == "White":
                loss = cp_before - cp_after
            else:
                loss = cp_after - cp_before
            loss = max(0.0, min(loss, LOSS_CAP_CP))

            move_records.append({
                "game_index": int(game_idx),
                "ply": int(plies[i]),
                "phase": phase_of_ply(int(plies[i]), total_plies),
                "side_to_move": mover,
                "move_san": sans[i],
                "best_move": bests[i],
                "fen_before": fens[i],
                "cp_before": cp_before,
                "cp_after": cp_after,
                "loss_cp": loss,
                "category": classify_loss(loss),
            })

    moves_df = pd.DataFrame(move_records)

    user_color_by_game = {row["index"]: row["color"] for _, row in games_df.iterrows()}
    moves_df["is_user_move"] = moves_df.apply(
        lambda r: user_color_by_game.get(r["game_index"]) == r["side_to_move"], axis=1
    )

    user_moves_all = moves_df[moves_df["is_user_move"]]

    # ─── Filtro de relevância ──────────────────────────────────────────────────
    # Aplicado a TODO o universo analítico (ACPL, score, by_phase, by_color, openings, Seção 7).
    # Win-rate e contagens de resultado ficam sobre o universo completo (histórico real).
    EARLY_TERMINATIONS = {"abandoned"}
    EARLY_TIMEOUT_RESIGN_MAX_PLIES = 30  # n_plies < 30 + termination time/resign = early
    MIN_RELEVANT_USER_MOVES = 25

    moves_per_game = user_moves_all.groupby("game_index").size().to_dict()
    termination_by_game = {
        int(row["index"]): str(row.get("termination") or "").lower()
        for _, row in games_df.iterrows()
    }

    def _relevance_decision(gi):
        n_user = moves_per_game.get(gi, 0)
        term = termination_by_game.get(gi, "")
        if n_user < MIN_RELEVANT_USER_MOVES:
            return False, "short"
        if term in EARLY_TERMINATIONS:
            return False, "abandoned"
        if term in {"timeout", "resigned"} and (n_user * 2) < EARLY_TIMEOUT_RESIGN_MAX_PLIES:
            return False, "early_timeout_resign"
        return True, None

    relevance_decisions = {gi: _relevance_decision(gi) for gi in range(1, n_games + 1)}
    relevant_game_indices = {gi for gi, (ok, _) in relevance_decisions.items() if ok}
    n_relevant = len(relevant_game_indices)
    filter_reasons = Counter(reason for ok, reason in relevance_decisions.values() if not ok)

    # Universo analítico: lances do usuário em partidas relevantes
    user_moves = user_moves_all[user_moves_all["game_index"].isin(relevant_game_indices)]

    overall_acpl = round(user_moves["loss_cp"].mean(), 2) if len(user_moves) else 0.0
    overall_accuracy = compute_accuracy(overall_acpl)

    by_phase = {}
    for ph in ["abertura", "meio-jogo", "final"]:
        sub = user_moves[user_moves["phase"] == ph]
        if len(sub):
            acpl_p = round(sub["loss_cp"].mean(), 2)
            by_phase[ph] = {
                "n_moves": int(len(sub)),
                "acpl": acpl_p,
                "accuracy": compute_accuracy(acpl_p),
                "score_10": compute_score10(acpl_p, depth, player_rating),
                "blunders": int((sub["category"] == "blunder").sum()),
                "mistakes": int((sub["category"] == "mistake").sum()),
                "inaccuracies": int((sub["category"] == "inaccuracy").sum()),
            }
        else:
            by_phase[ph] = {"n_moves": 0, "acpl": 0, "accuracy": 0, "score_10": 0,
                            "blunders": 0, "mistakes": 0, "inaccuracies": 0}

    cat_counts = Counter(user_moves["category"].tolist())

    # Por time_class (rapid/daily/blitz/bullet): KPIs separados.
    # Útil porque Daily (horas/lance) infla score; bullet (segundos) deflaciona.
    by_time_class = {}
    if "time_class" in games_df.columns:
        for tc, sub_g in games_df.groupby("time_class"):
            tc_str = str(tc).strip()
            if not tc_str or tc_str == "nan":
                continue
            n = int(len(sub_g))
            w = int((sub_g["result"] == "Win").sum())
            l = int((sub_g["result"] == "Loss").sum())
            d = int((sub_g["result"] == "Draw").sum())
            n_rel = int(sub_g["index"].isin(relevant_game_indices).sum())
            sub_m = user_moves[user_moves["game_index"].isin(sub_g["index"])]
            acpl_tc = round(sub_m["loss_cp"].mean(), 2) if len(sub_m) else 0.0
            by_time_class[tc_str] = {
                "games": n,
                "games_relevant": n_rel,
                "wins": w, "losses": l, "draws": d,
                "win_rate": round(100 * w / n, 1) if n else 0,
                "acpl": acpl_tc,
                "score_10": compute_score10(acpl_tc, depth, player_rating),
                "blunders": int((sub_m["category"] == "blunder").sum()) if len(sub_m) else 0,
                "mistakes": int((sub_m["category"] == "mistake").sum()) if len(sub_m) else 0,
            }

    wins = int((games_df["result"] == "Win").sum())
    losses = int((games_df["result"] == "Loss").sum())
    draws = int((games_df["result"] == "Draw").sum())
    win_rate = round(100 * wins / n_games, 1) if n_games else 0.0

    by_color = {}
    for color in ["White", "Black"]:
        sub_g = games_df[games_df["color"] == color]
        if len(sub_g):
            w = int((sub_g["result"] == "Win").sum())
            l = int((sub_g["result"] == "Loss").sum())
            d = int((sub_g["result"] == "Draw").sum())
            # ACPL: só sobre partidas relevantes dessa cor
            sub_m = user_moves[user_moves["game_index"].isin(sub_g["index"])]
            n_rel = int(sub_g["index"].isin(relevant_game_indices).sum())
            acpl_c = round(sub_m["loss_cp"].mean(), 2) if len(sub_m) else 0.0
            by_color[color] = {
                "games": int(len(sub_g)),
                "games_relevant": n_rel,
                "wins": w, "losses": l, "draws": d,
                "win_rate": round(100 * w / len(sub_g), 1),
                "acpl": acpl_c,
                "accuracy": compute_accuracy(acpl_c),
                "score_10": compute_score10(acpl_c, depth, player_rating),
            }
        else:
            by_color[color] = {"games": 0, "games_relevant": 0, "wins": 0, "losses": 0, "draws": 0,
                               "win_rate": 0, "acpl": 0, "accuracy": 0, "score_10": 0}

    def _clean_str(v):
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()

    if "eco_family" in games_df.columns:
        games_df["_family_key"] = games_df.apply(
            lambda r: _clean_str(r.get("eco_family"))
                      or _clean_str(r.get("opening")).split(":")[0].strip()
                      or "Sem ECO", axis=1)
    else:
        games_df["_family_key"] = games_df["opening"].map(
            lambda v: (_clean_str(v) or "Sem ECO").split(":")[0].strip() or "Sem ECO")

    user_moves_keyed = user_moves.merge(
        games_df[["index", "_family_key"]],
        left_on="game_index", right_on="index", how="left",
    )

    def _agg_by(key_col):
        out = {}
        # ACPL: vem de user_moves_keyed que já está filtrado para partidas relevantes
        acpl_grp = user_moves_keyed.groupby(key_col)["loss_cp"].mean().round(2).to_dict()
        # Counts: sobre todas as partidas (record histórico)
        for key, sub in games_df.groupby(key_col):
            n = len(sub)
            w = int((sub["result"] == "Win").sum())
            l = int((sub["result"] == "Loss").sum())
            d = int((sub["result"] == "Draw").sum())
            n_rel = int(sub["index"].isin(relevant_game_indices).sum())
            ply_series = pd.to_numeric(sub.get("eco_ply"), errors="coerce") if "eco_ply" in sub.columns else pd.Series([], dtype=float)
            ply_clean = ply_series.dropna() if len(ply_series) else ply_series
            avg_ply = round(float(ply_clean.mean()), 1) if len(ply_clean) else None
            acpl_val = acpl_grp.get(key)
            out[key] = {
                "name": key, "n": n, "n_relevant": n_rel,
                "wins": w, "losses": l, "draws": d,
                "win_rate": round(100 * w / n, 1) if n else 0,
                "acpl": acpl_val,
                "score_10": compute_score10(acpl_val, depth, player_rating) if acpl_val is not None else None,
                "avg_eco_ply": avg_ply,
            }
        return out

    family_stats = _agg_by("_family_key")

    openings_by_family = sorted(family_stats.values(), key=lambda x: -x["n"])[:10]
    openings_weak_spots = sorted(
        [v for v in family_stats.values() if v["n"] >= 5 and v["win_rate"] < 40.0],
        key=lambda x: (x["win_rate"], -x["n"]),
    )

    eco_ply_series = pd.to_numeric(games_df.get("eco_ply"), errors="coerce") if "eco_ply" in games_df.columns else pd.Series([], dtype=float)
    eco_ply_clean = eco_ply_series.dropna() if len(eco_ply_series) else eco_ply_series
    avg_eco_ply_overall = round(float(eco_ply_clean.mean()), 1) if len(eco_ply_clean) else None
    avg_eco_ply_by_color = {}
    for c in ["White", "Black"]:
        sub_ply = pd.to_numeric(games_df.loc[games_df["color"] == c].get("eco_ply"), errors="coerce") if "eco_ply" in games_df.columns else pd.Series([], dtype=float)
        sub_clean = sub_ply.dropna() if len(sub_ply) else sub_ply
        avg_eco_ply_by_color[c] = round(float(sub_clean.mean()), 1) if len(sub_clean) else None
    eco_coverage = round(100 * len(eco_ply_clean) / n_games, 1) if n_games else 0.0

    opp_counter = Counter(games_df["opponent"].dropna().tolist())
    head_to_head = []
    for opp, n in opp_counter.most_common(10):
        sub = games_df[games_df["opponent"] == opp]
        head_to_head.append({
            "opponent": opp,
            "games": int(len(sub)),
            "wins": int((sub["result"] == "Win").sum()),
            "losses": int((sub["result"] == "Loss").sum()),
            "draws": int((sub["result"] == "Draw").sum()),
            "avg_opp_rating": int(pd.to_numeric(sub["opponent_rating"], errors="coerce").dropna().mean()) if len(sub) else 0,
        })

    game_metrics = []
    for gi, group in moves_df.groupby("game_index"):
        user_sub = group[group["is_user_move"]]
        if len(user_sub) == 0:
            continue
        acpl_g = round(user_sub["loss_cp"].mean(), 2)
        worst_idx = user_sub["loss_cp"].idxmax()
        worst = user_sub.loc[worst_idx]
        meta = games_lookup.get(int(gi), {})
        game_metrics.append({
            "game_index": int(gi),
            "result": meta.get("result"),
            "color": meta.get("color"),
            "opponent": meta.get("opponent"),
            "opponent_rating": safe_int(meta.get("opponent_rating")),
            "date": meta.get("date"),
            "url": meta.get("url"),
            "time_class": meta.get("time_class"),
            "termination": (meta.get("termination") or "").strip(),
            "acpl": acpl_g,
            "accuracy": compute_accuracy(acpl_g),
            "score_10": compute_score10(acpl_g, depth, player_rating),
            "n_user_moves": int(len(user_sub)),
            "blunders": int((user_sub["category"] == "blunder").sum()),
            "mistakes": int((user_sub["category"] == "mistake").sum()),
            "worst_move": {
                "ply": int(worst["ply"]),
                "san": worst["move_san"],
                "best": worst["best_move"],
                "loss_cp": round(float(worst["loss_cp"]), 1),
                "fen_before": worst["fen_before"],
            },
        })

    wins_g = [g for g in game_metrics if g["result"] == "Win"]
    losses_g = [g for g in game_metrics if g["result"] == "Loss"]

    # Reutiliza o filtro de relevância global: paradigmáticas só vêm de partidas relevantes.
    relevant_wins = [g for g in wins_g if g["game_index"] in relevant_game_indices]
    relevant_losses = [g for g in losses_g if g["game_index"] in relevant_game_indices]

    # Fallback: se filtro derrubou amostra demais, relaxa (ordena por mais lances primeiro).
    if len(relevant_wins) < 2:
        relevant_wins = sorted(wins_g, key=lambda g: -g["n_user_moves"])
    if len(relevant_losses) < 2:
        relevant_losses = sorted(losses_g, key=lambda g: -g["n_user_moves"])

    # Top 5 vitórias: jogou mais preciso (score alto) contra adversário forte (rating alto)
    best_wins_top5 = sorted(
        relevant_wins,
        key=lambda g: (-g["accuracy"], -g["opponent_rating"]),
    )[:5]

    # Top 5 derrotas: jogou pior (score baixo) contra adversário fraco (rating baixo);
    # critério secundário: maior blunder único.
    worst_losses_top5 = sorted(
        relevant_losses,
        key=lambda g: (g["score_10"], g["opponent_rating"], -g["worst_move"]["loss_cp"]),
    )[:5]

    # Paradigmáticas (Seção 7): só as 2 melhores vitórias + 2 piores derrotas (4 partidas detalhadas)
    paradigmatic = best_wins_top5[:2] + worst_losses_top5[:2]

    OPENING_SKIP_PLIES = 8  # ignora 8 primeiros plies (livro de abertura) na busca de lances decisivos
    SWING_MIN_CP = 30        # swing mínimo p/ ser considerado "real"; abaixo disso, vai pra fallback distribuído

    def _decisive_positions(game_index, user_color, result, n=3):
        """3 lances onde a posição mais virou na direção do vencedor.
        Para vitória do usuário: maiores ganhos do usuário (eval mudou a favor dele).
        Para derrota do usuário: maiores ganhos do adversário."""
        g = moves_df[(moves_df["game_index"] == game_index) & (moves_df["ply"] > OPENING_SKIP_PLIES)].copy()
        if len(g) == 0:
            g = moves_df[moves_df["game_index"] == game_index].copy()
        if len(g) == 0:
            return []

        user_is_white = (user_color == "White")
        user_won = (result == "Win")
        # eval (cp) é perspectiva das brancas; swing positivo = ganho das brancas
        sign = 1 if (user_is_white == user_won) else -1
        g["swing"] = (g["cp_after"] - g["cp_before"]) * sign

        g_clean = g.dropna(subset=["swing"])
        max_swing = g_clean["swing"].max() if len(g_clean) else None
        if max_swing is not None and not pd.isna(max_swing) and max_swing >= SWING_MIN_CP:
            top = g_clean.nlargest(n, "swing")
        else:
            # Fallback: distribui n posições nos 50%/75%/95% do percurso (partida lisa, sem viradas)
            ply_max = int(g["ply"].max())
            chosen = []
            for f in (0.50, 0.75, 0.95)[:n]:
                target = max(OPENING_SKIP_PLIES + 1, int(ply_max * f))
                row = g[g["ply"] >= target].head(1)
                if len(row):
                    chosen.append(row)
            top = pd.concat(chosen) if chosen else g.head(n)

        top = top.sort_values("ply")
        out = []
        for _, r in top.iterrows():
            out.append({
                "ply": int(r["ply"]),
                "phase": r["phase"],
                "side_to_move": r["side_to_move"],
                "is_user_move": bool(r["is_user_move"]),
                "san": r["move_san"],
                "best": r["best_move"],
                "loss_cp": round(float(r["loss_cp"]), 1),
                "swing_cp": round(float(r["swing"]), 1) if "swing" in r else 0.0,
                "fen_before": r["fen_before"],
            })
        return out

    for pg in paradigmatic:
        pg["key_positions"] = _decisive_positions(pg["game_index"], pg["color"], pg["result"])
        # Detecta padrões estruturais usando o FEN do meio do jogo (~ply 24, ou último disponível)
        pg_moves = moves_df[moves_df["game_index"] == pg["game_index"]].sort_values("ply")
        if len(pg_moves):
            mid_idx = min(len(pg_moves) - 1, max(0, len(pg_moves) // 2))
            mid_fen = pg_moves.iloc[mid_idx]["fen_before"]
            pg["position_features"] = detect_position_features(str(mid_fen))
        else:
            pg["position_features"] = []

    # Seção 13 (Partidas analisadas): top 5 vitórias + top 5 derrotas, com label rico (V/D + score + adversário)
    references = []
    for pg in best_wins_top5:
        if pg.get("url"):
            references.append({
                "label": f"V #{pg['game_index']} vs {pg['opponent']} ({pg['opponent_rating']}) — score {pg['score_10']}/10",
                "url": pg["url"],
            })
    for pg in worst_losses_top5:
        if pg.get("url"):
            references.append({
                "label": f"D #{pg['game_index']} vs {pg['opponent']} ({pg['opponent_rating']}) — score {pg['score_10']}/10",
                "url": pg["url"],
            })

    previous = load_previous_computed(username, stamp)
    delta = None
    if previous and previous.get("kpis"):
        prev_kpis = previous["kpis"]
        delta = {
            "previous_date": previous.get("stamp"),
            "acpl_delta": round(overall_acpl - prev_kpis.get("acpl", overall_acpl), 2),
            "accuracy_delta": round(overall_accuracy - prev_kpis.get("accuracy", overall_accuracy), 2),
            "win_rate_delta": round(win_rate - prev_kpis.get("win_rate", win_rate), 2),
        }

    # Tier baseado em n_relevant (universo analítico)
    if n_relevant < 10:
        sample_tier = "preliminar"
    elif n_relevant < 30:
        sample_tier = "adequado"
    else:
        sample_tier = "robusto"
    if depth is not None and depth < 10:
        depth_tier = "raso"
    elif depth is not None and depth < 15:
        depth_tier = "aceitavel"
    else:
        depth_tier = "robusto"
    sample_warnings = []
    if n_relevant < 10:
        sample_warnings.append(f"Apenas {n_relevant} partidas relevantes (de {n_games} coletadas) — afirmações categóricas devem ser evitadas; trate como tendência, não diagnóstico.")
    n_filtered = n_games - n_relevant
    if n_games > 0 and n_filtered > 0:
        sample_warnings.append(
            f"{n_relevant} de {n_games} partidas consideradas relevantes para análise deste relatório (as outras {n_filtered} foram curtas, abandonos ou early timeout/resign)."
        )
    if depth is not None and depth < 10:
        sample_warnings.append(f"Depth {depth} é raso para magnitude de imprecisões; use só para detectar erros graves.")
    games_white = int((games_df["color"] == "White").sum())
    games_black = int((games_df["color"] == "Black").sum())
    if games_white < 8 or games_black < 8:
        sample_warnings.append(f"Distribuição por cor desbalanceada ({games_white}B / {games_black}P); evite conclusões fortes sobre assimetria.")
    time_classes = sorted({str(tc) for tc in games_df.get("time_class", []) if isinstance(tc, str) and tc})
    if time_classes == ["bullet"]:
        sample_warnings.append("Amostra 100% bullet — ACPL tende a ser pior que em rapid; resultados não generalizam para formatos lentos.")
    if eco_coverage < 80 and n_games >= 10:
        sample_warnings.append(f"Cobertura ECO de {eco_coverage}% — parte das partidas não foi classificada via base Lichess; análise de repertório fica parcial.")

    confidence_pct = compute_confidence_pct(n_relevant, depth, eco_coverage)

    # Calibração de score (transparência): mostra como score foi derivado de ACPL+depth+rating
    df_eq = depth_factor(depth)
    exp_acpl = round(expected_acpl(player_rating), 1)
    acpl_d20_eq = round(overall_acpl / df_eq, 2) if df_eq > 0 else overall_acpl
    perf_ratio = round(acpl_d20_eq / exp_acpl, 2) if exp_acpl > 0 else None
    score_calibration = {
        "player_rating": player_rating,
        "rating_basis": rating_basis,
        "depth": depth,
        "depth_factor": round(df_eq, 2),
        "acpl_observed": overall_acpl,
        "acpl_d20_equivalent": acpl_d20_eq,
        "expected_acpl_for_rating": exp_acpl,
        "performance_ratio": perf_ratio,
    }

    puzzle_program = derive_puzzle_program(
        games_df=games_df,
        by_phase=by_phase,
        kpis={"blunders": cat_counts.get("blunder", 0), "mistakes": cat_counts.get("mistake", 0)},
        head_to_head=head_to_head,
        time_classes=time_classes,
    )

    payload = {
        "username": username,
        "stamp": stamp,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_games_csv": games_path.name,
        "source_analysis_csv": analysis_path.name,
        "stockfish_depth": depth,
        "sample_quality": {
            "tier": sample_tier,
            "depth_tier": depth_tier,
            "confidence_pct": confidence_pct,
            "n_games_collected": n_games,
            "n_games_relevant": n_relevant,
            "n_games_filtered": n_games - n_relevant,
            "filter_reasons": dict(filter_reasons),
            "filter_thresholds": {
                "min_user_moves": MIN_RELEVANT_USER_MOVES,
                "early_timeout_resign_max_plies": EARLY_TIMEOUT_RESIGN_MAX_PLIES,
                "always_excluded_terminations": sorted(EARLY_TERMINATIONS),
            },
            "time_classes": time_classes,
            "games_white": games_white,
            "games_black": games_black,
            "warnings": sample_warnings,
        },
        "kpis": {
            "n_games": n_games,
            "n_positions_analyzed": n_positions,
            "wins": wins, "losses": losses, "draws": draws,
            "win_rate": win_rate,
            "acpl": overall_acpl,
            "accuracy": overall_accuracy,
            "score_10": compute_score10(overall_acpl, depth, player_rating),
            "blunders": cat_counts.get("blunder", 0),
            "mistakes": cat_counts.get("mistake", 0),
            "inaccuracies": cat_counts.get("inaccuracy", 0),
            "good_moves": cat_counts.get("good", 0),
        },
        "by_phase": by_phase,
        "by_color": by_color,
        "by_time_class": by_time_class,
        "openings_by_family": openings_by_family,
        "openings_weak_spots": openings_weak_spots,
        "eco_stats": {
            "coverage_pct": eco_coverage,
            "avg_eco_ply": avg_eco_ply_overall,
            "avg_eco_ply_by_color": avg_eco_ply_by_color,
        },
        "puzzle_program": puzzle_program,
        "score_calibration": score_calibration,
        "head_to_head": head_to_head,
        "paradigmatic_games": paradigmatic,
        "references": references,
        "delta_vs_previous": delta,
    }

    out_path = DATA_DIR / f"{username}_{stamp}_computed.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # Persistência longitudinal (SQLite); falha silenciosa não deve quebrar o pipeline
    try:
        from history import open_db, record_analysis
        conn = open_db(DATA_DIR / "history.db")
        record_analysis(conn, payload, perspective=None)
        conn.close()
    except Exception as e:
        print(f"⚠ histórico não gravado: {e}")

    print(f"✅ {out_path}")
    print(f"   ACPL={overall_acpl} | accuracy={overall_accuracy}% | "
          f"W/L/D={wins}/{losses}/{draws} | partidas paradigmáticas={len(paradigmatic)}")


if __name__ == "__main__":
    main()

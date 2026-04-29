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

# Importa detectores estruturais do módulo dedicado.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from position_facts import detect_facts as detect_position_facts, fact_keys  # type: ignore

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


_ACPL_ANCHORS_CHESSCOM = [
    # ACPL típico observado em chess.com online por faixa de rating, em depth 20.
    # Fonte: âncoras pragmáticas calibradas com a literatura pública (Lichess
    # insights e cheat-detection notes). Reflete que jogadores online cometem
    # mais erros do que torneios clássicos no mesmo rating: um 1400 chess.com
    # joga ACPL ~80, não 40 como a fórmula teórica antiga sugeria.
    (800, 150), (1000, 120), (1200, 95), (1400, 80),
    (1600, 65), (1800, 50), (2000, 40), (2200, 30),
    (2400, 23), (2500, 20), (2700, 15),
]


def expected_acpl(rating: float | int) -> float:
    """ACPL típico esperado para um rating chess.com (referência depth=20).
    Interpolação linear entre âncoras empíricas; saturação ≥15 cp (limite GM)."""
    if rating is None or rating <= 0:
        rating = 1200
    r = float(rating)
    if r <= _ACPL_ANCHORS_CHESSCOM[0][0]:
        return _ACPL_ANCHORS_CHESSCOM[0][1]
    if r >= _ACPL_ANCHORS_CHESSCOM[-1][0]:
        return _ACPL_ANCHORS_CHESSCOM[-1][1]
    for (r1, a1), (r2, a2) in zip(_ACPL_ANCHORS_CHESSCOM, _ACPL_ANCHORS_CHESSCOM[1:]):
        if r1 <= r <= r2:
            return a1 + (a2 - a1) * (r - r1) / (r2 - r1)
    return 50.0


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


def engine_suspicion_factor(ratio_acpl_to_expected: float | None,
                            n_user_moves: int | None) -> float:
    """Fator multiplicativo (0.5–1.0) aplicado ao Score quando ACPL é
    implausivelmente baixo para o rating do jogador (sinal de motor).

    Definição: humanos jogam ACPL próximo do esperado pra seu rating. Quando
    o ratio (ACPL_d20_eq / expected_acpl) cai muito abaixo de 0.5, o jogador
    está jogando bem demais — provável uso de motor. Score é descontado
    proporcionalmente até o piso 0.5.

      ratio ≥ 0.5  → fator 1.0  (sem penalidade)
      ratio = 0.3  → fator 0.8
      ratio = 0.1  → fator 0.6
      ratio ≤ 0.0  → fator 0.5  (piso)

    Só aplica em amostra ≥100 lances (evita falso positivo em partidas curtas
    onde 1 ou 2 lances perfeitos abaixam o ACPL artificialmente).
    """
    if (ratio_acpl_to_expected is None or n_user_moves is None
            or n_user_moves < 100):
        return 1.0
    if ratio_acpl_to_expected >= 0.5:
        return 1.0
    return max(0.5, 0.5 + float(ratio_acpl_to_expected))


def compute_score10(acpl, depth=None, rating=None,
                    win_rate=None, blunders=None, n_user_moves=None):
    """Score 0-10 — blend ponderado de 3 componentes + penalidade de motor.

    50% — ACPL relativo: ACPL_d20_eq / expected_acpl(rating). Curva chess.com
          empírica. Score do componente: exp(-ratio/2). 1.0 = perfeito.
    30% — Win-rate: win_rate / 100. 1.0 = ganhou tudo.
    20% — Redução de blunders: 1 / (1 + bpm/5).

    Penalidade de motor (engine_suspicion_factor): aplicada multiplicativamente
    ao blend quando ratio < 0.5 e n_user_moves ≥ 100. ACPL absurdamente baixo
    para o rating do jogador é descontado até 50% do Score.

    Compatibilidade: chamadas legadas que passam só (acpl, depth, rating)
    recebem só o componente ACPL × 10 com a penalty já aplicada.
    """
    import math
    if acpl is None or acpl < 0:
        return 0.0

    # Componente A — ACPL relativo
    df = depth_factor(depth) if depth is not None else 1.0
    acpl_eq = float(acpl) / df if df > 0 else float(acpl)
    expected = expected_acpl(rating)
    ratio = acpl_eq / expected if expected > 0 else 0
    acpl_score = math.exp(-ratio / 2)

    # Penalidade de motor (aplicada ao Score final)
    engine_factor = engine_suspicion_factor(ratio, n_user_moves)

    # Sem win_rate disponível: retorna só componente A (compatibilidade)
    if win_rate is None:
        return round(10 * acpl_score * engine_factor, 1)

    # Componente win-rate
    win_score = max(0.0, min(1.0, float(win_rate) / 100.0))

    # Componente blunder-reduction
    if blunders is not None and n_user_moves and int(n_user_moves) > 0:
        bpm = (float(blunders) / float(n_user_moves)) * 100
        blunder_score = 1.0 / (1.0 + bpm / 5.0)
    else:
        blunder_score = 0.5  # neutro

    blend = 0.5 * acpl_score + 0.3 * win_score + 0.2 * blunder_score
    return round(10 * blend * engine_factor, 1)


def competitive_window(rating: int | float | None) -> int:
    """Janela de Elo para 'partidas competitivas': ±max(150, 10% do rating).
    150 evita janela estreita demais para iniciantes; 10% acompanha mestres."""
    if not rating or rating <= 0:
        return 150
    return int(max(150, round(0.10 * float(rating))))


def score_uncertainty_band(depth: int | None) -> float:
    """Faixa ± de incerteza no Score, função de depth.

    Motor raso (d<12) sub-detecta erros. A `depth_factor` já compensa o ACPL médio
    em valor esperado, mas cada partida individualmente pode ter desvio grande,
    e o ratio final é não-linear. Este band quantifica essa incerteza:

      d10 → ±1.5  (mostre Score como faixa, não ponto)
      d12 → ±1.0
      d15 → ±0.5
      d18+→ ±0.2  (negligível)

    Use no texto: 'Score 0,3 (faixa por depth raso: 0,3 – 2,0)'.
    """
    if depth is None:
        return 1.0
    if depth >= 18:
        return 0.2
    if depth >= 15:
        return 0.5
    if depth >= 12:
        return 1.0
    return 1.5


def compute_score_trio(loss_cps, opp_ratings, depth, player_rating, comp_window,
                       categories=None, results_per_move=None):
    """Calcula (geral, competitivo, ponderado) sobre um conjunto de lances.

    Inputs:
      - loss_cps: pd.Series de loss_cp por lance
      - opp_ratings: pd.Series alinhada, opponent_rating por lance
      - depth, player_rating, comp_window
      - categories: pd.Series alinhada com category ('blunder'/'mistake'/'inaccuracy'/'good')
      - results_per_move: pd.Series alinhada com result da partida ('Win'/'Loss'/'Draw')

    Quando categories e results_per_move estão disponíveis, o score blend
    (50% ACPL + 30% win-rate + 20% blunders) é aplicado em cada variante
    com seus respectivos subsets.

    Returns: dict com acpl_*, score_10_*, win_rate_*, blunders_*, n_*_moves.
    """
    import math as _math
    out = {
        "acpl_overall": None, "score_10_overall": None,
        "acpl_competitive": None, "score_10_competitive": None, "n_competitive_moves": 0,
        "acpl_weighted": None, "score_10_weighted": None, "n_eff_weighted": 0.0,
    }
    if len(loss_cps) == 0:
        return out

    has_cat = categories is not None and len(categories) == len(loss_cps)
    has_res = results_per_move is not None and len(results_per_move) == len(loss_cps)

    def _win_rate(mask=None):
        if not has_res: return None
        sub = results_per_move if mask is None else results_per_move[mask]
        if not len(sub): return None
        # win_rate calculado em base de lances (não partidas) — proxy bom porque
        # cada partida contribui proporcional ao seu nº de lances do user
        wins = (sub == "Win").sum()
        return round(100 * float(wins) / len(sub), 1)

    def _blunder_count(mask=None):
        if not has_cat: return None
        sub = categories if mask is None else categories[mask]
        return int((sub == "blunder").sum())

    # Overall
    out["acpl_overall"] = round(float(loss_cps.mean()), 2)
    out["score_10_overall"] = compute_score10(
        out["acpl_overall"], depth, player_rating,
        win_rate=_win_rate(), blunders=_blunder_count(), n_user_moves=len(loss_cps),
    )

    if player_rating and len(opp_ratings) and opp_ratings.notna().any():
        opp_clean = opp_ratings.fillna(player_rating)
        gap = (opp_clean - player_rating).abs()
        comp_mask = gap <= comp_window
        n_comp = int(comp_mask.sum())
        if n_comp >= 5:
            comp_acpl = round(float(loss_cps[comp_mask].mean()), 2)
            out["acpl_competitive"] = comp_acpl
            out["score_10_competitive"] = compute_score10(
                comp_acpl, depth, player_rating,
                win_rate=_win_rate(comp_mask),
                blunders=_blunder_count(comp_mask), n_user_moves=n_comp,
            )
            out["n_competitive_moves"] = n_comp

        weights = ((opp_clean - player_rating) / 300.0).apply(lambda x: _math.exp(-(x ** 2)))
        sum_w = float(weights.sum())
        if sum_w > 0:
            wacpl = round(float((loss_cps * weights).sum() / sum_w), 2)
            # win-rate ponderado: cada lance vencedor conta pelo seu peso
            if has_res:
                wins_w = float(((results_per_move == "Win").astype(float) * weights).sum())
                w_winrate = round(100 * wins_w / sum_w, 1) if sum_w > 0 else None
            else:
                w_winrate = None
            out["acpl_weighted"] = wacpl
            out["score_10_weighted"] = compute_score10(
                wacpl, depth, player_rating,
                win_rate=w_winrate,
                blunders=_blunder_count(), n_user_moves=int(round(sum_w)),
            )
            out["n_eff_weighted"] = round(sum_w, 1)
    return out


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


def load_from_db(username: str) -> tuple[pd.DataFrame, pd.DataFrame, int | None, str]:
    """Materializa games_df + an_df + depth a partir de history.db.
    Retorna formato compatível com o pipeline CSV (mesmas colunas)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import history  # type: ignore
    db_path = DATA_DIR / "history.db"
    if not db_path.exists():
        raise SystemExit(f"❌ history.db não encontrado em {db_path} — rode scripts/serve.py primeiro.")
    conn = history.open_db(db_path)
    games_rows = history.fetch_games(conn, username)
    if not games_rows:
        raise SystemExit(f"❌ nenhuma partida em history.db para {username}.")
    analyses_rows = history.fetch_analyses_for_user(conn, username, min_depth=0)
    conn.close()
    if not analyses_rows:
        raise SystemExit(f"❌ partidas existem para {username}, mas nenhuma análise foi salva ainda.")

    games_df = pd.DataFrame(games_rows)
    # game_index sequencial alinhado com a ordem cronológica de fetch_games
    gid_to_idx = {gid: i + 1 for i, gid in enumerate(games_df["game_id"].tolist())}
    games_df["index"] = games_df["game_id"].map(gid_to_idx)

    an_df = pd.DataFrame(analyses_rows)
    an_df["game_index"] = an_df["game_id"].map(gid_to_idx)
    # Pipeline espera colunas: game_index, ply, side_to_move, move_san, move_uci,
    # fen_before, depth, evaluation, mate, best_move, continuation, tactical_*
    # game_analyses já tem todas. Ordena.
    an_df = an_df.sort_values(["game_index", "ply"]).reset_index(drop=True)

    depth_min = int(an_df["depth"].min()) if len(an_df) else None
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return games_df, an_df, depth_min, stamp


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Uso: python compute.py <username> [--from-db]")
    username = sys.argv[1].strip()
    from_db = "--from-db" in sys.argv[2:]
    if not DATA_DIR.is_dir():
        raise SystemExit(f"❌ Pasta de dados não encontrada: {DATA_DIR}")

    if from_db:
        print(f"📦 lendo de history.db (modo --from-db)")
        games_df, an_df, depth, stamp = load_from_db(username)
        # game_id estável; quando há mistura de depths, pega o mínimo (mais conservador)
        # — confidence_pct usa esse depth pra calibração.
        games_path = analysis_path = None
    else:
        games_path, analysis_path, stamp = find_latest_csvs(username)
        print(f"📁 games:    {games_path.name}")
        print(f"📁 analysis: {analysis_path.name}")
        games_df = pd.read_csv(games_path)
        an_df = pd.read_csv(analysis_path)
        depth_match = re.search(r"_d(\d+)(?:[_.])", analysis_path.name)
        depth = int(depth_match.group(1)) if depth_match else None

    n_games = len(games_df)
    n_positions = len(an_df)
    if "index" not in games_df.columns:
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
        themes = group.get("tactical_theme", pd.Series([""] * total_plies)).fillna("").tolist()
        confs = group.get("tactical_confidence", pd.Series([""] * total_plies)).fillna("").tolist()
        sources = group.get("tactical_source", pd.Series([""] * total_plies)).fillna("").tolist()
        # game_id pode vir do CSV (modo arquivado) ou do DB (modo --from-db).
        # No primeiro caso é a URL chess.com da partida; no segundo é a PK do row.
        gids_col = group.get("game_id", pd.Series([None] * total_plies)).tolist()
        # Cache de position_facts já gravado no DB (modo --from-db). String JSON ou vazio.
        cached_facts = group.get("position_facts", pd.Series([""] * total_plies)).fillna("").tolist()

        for i in range(total_plies):
            cp_before = cps[i]
            cp_after = cps[i + 1] if i + 1 < total_plies else cp_before
            mover = sides[i]
            if mover == "White":
                loss = cp_before - cp_after
            else:
                loss = cp_after - cp_before
            loss = max(0.0, min(loss, LOSS_CAP_CP))

            # Position facts: rodar em todo lance com loss >= 50 (qualquer
            # erro ≥ inaccuracy). Reusa cache do DB se houver.
            facts_list: list[dict] = []
            facts_were_computed = False
            if loss >= 50:
                cached = cached_facts[i] if i < len(cached_facts) else ""
                if cached and isinstance(cached, str):
                    try:
                        facts_list = json.loads(cached) or []
                    except Exception:
                        facts_list = []
                if not facts_list:
                    try:
                        facts_list = detect_position_facts(str(fens[i]))
                        facts_were_computed = True
                    except Exception:
                        facts_list = []

            move_records.append({
                "game_index": int(game_idx),
                "game_id": gids_col[i] if i < len(gids_col) else None,
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
                "tactical_theme": str(themes[i]) if i < len(themes) else "",
                "tactical_confidence": confs[i] if i < len(confs) else "",
                "tactical_source": str(sources[i]) if i < len(sources) else "",
                "position_facts": facts_list,
                "_facts_computed_now": facts_were_computed,
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
    user_moves = user_moves_all[user_moves_all["game_index"].isin(relevant_game_indices)].copy()

    # Anota result da partida em cada lance pra alimentar o blend (Win/Loss/Draw).
    result_by_game_index = {int(row["index"]): row["result"] for _, row in games_df.iterrows()}
    user_moves["game_result"] = user_moves["game_index"].map(result_by_game_index)

    def _subset_metrics(subset_moves):
        """Retorna (acpl, win_rate, blunders, n_moves) pra rodar score blend."""
        if not len(subset_moves):
            return None, None, None, 0
        acpl = round(float(subset_moves["loss_cp"].mean()), 2)
        n = int(len(subset_moves))
        blunders = int((subset_moves["category"] == "blunder").sum())
        wins = int((subset_moves["game_result"] == "Win").sum())
        win_rate = round(100 * wins / n, 1) if n else None
        return acpl, win_rate, blunders, n

    overall_acpl = round(user_moves["loss_cp"].mean(), 2) if len(user_moves) else 0.0
    overall_accuracy = compute_accuracy(overall_acpl)
    _, overall_win_rate_moves, overall_blunders, overall_n_moves = _subset_metrics(user_moves)

    # ── Score competitivo: subset de partidas com adversário em janela ±max(150, 10% rating) ──
    # Motivação: rating médio + adversários muito desbalanceados distorcem o expected_acpl.
    # Farming contra fracos (jogador relaxa) ou enfrentar técnicos (sub-rating) levam a Score
    # artificialmente alto/baixo. Filtrar pra adversários do mesmo nível dá um número honesto.
    comp_window = competitive_window(player_rating)
    if "opponent_rating" in games_df.columns and player_rating:
        opp_r_series = pd.to_numeric(games_df["opponent_rating"], errors="coerce")
        competitive_mask = opp_r_series.notna() & (
            (opp_r_series - player_rating).abs() <= comp_window
        )
        competitive_game_indices = set(games_df.loc[competitive_mask, "index"].tolist())
        competitive_game_indices &= relevant_game_indices  # só relevantes
    else:
        competitive_game_indices = set()
    n_competitive = len(competitive_game_indices)
    competitive_user_moves = user_moves[user_moves["game_index"].isin(competitive_game_indices)]
    if len(competitive_user_moves) and n_competitive >= 5:
        c_acpl, c_winrate, c_blunders, c_nmoves = _subset_metrics(competitive_user_moves)
        competitive_acpl = c_acpl
        competitive_score = compute_score10(c_acpl, depth, player_rating,
                                            win_rate=c_winrate,
                                            blunders=c_blunders,
                                            n_user_moves=c_nmoves)
    else:
        competitive_acpl = None
        competitive_score = None

    # ── Score ponderado: cada partida pesa exp(-(gap/300)²) no agregado ──
    # Não descarta partidas; só dilui as menos representativas. Mesma faixa: peso 1.0;
    # ±300 Elo: peso 0.37; ±500: peso 0.06. Mais robusto que cutoff binário porque
    # aproveita partidas borderline e suaviza outliers do cutoff competitivo.
    import math as _math
    WEIGHT_SIGMA = 300.0
    if "opponent_rating" in games_df.columns and player_rating:
        opp_r_map = pd.to_numeric(games_df.set_index("index")["opponent_rating"], errors="coerce").to_dict()
        def _game_weight(gi):
            opp = opp_r_map.get(gi)
            if opp is None or pd.isna(opp):
                return 0.0
            gap = float(opp) - float(player_rating)
            return _math.exp(-(gap / WEIGHT_SIGMA) ** 2)
        weights_per_move = user_moves["game_index"].map(_game_weight).fillna(0.0)
        sum_w = float(weights_per_move.sum())
        if sum_w > 0:
            weighted_acpl = round(float((user_moves["loss_cp"] * weights_per_move).sum() / sum_w), 2)
            # win-rate ponderado: vitória conta pelo peso da partida (gap menor = peso maior)
            wins_w = float(((user_moves["game_result"] == "Win").astype(float) * weights_per_move).sum())
            weighted_winrate = round(100 * wins_w / sum_w, 1) if sum_w > 0 else None
            weighted_score = compute_score10(weighted_acpl, depth, player_rating,
                                             win_rate=weighted_winrate,
                                             blunders=overall_blunders,
                                             n_user_moves=int(round(sum_w)))
            game_weights = pd.Series({gi: _game_weight(gi) for gi in relevant_game_indices})
            n_eff_weighted = round(float(game_weights.sum()), 1)
        else:
            weighted_acpl = None
            weighted_score = None
            n_eff_weighted = 0.0
    else:
        weighted_acpl = None
        weighted_score = None
        n_eff_weighted = 0.0

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

    # ── Agregados de fatos estruturais (position_facts) ──────────────
    # Roda detect_position_facts no FEN do worst_move de cada partida e
    # agrega: top fatos absolutos + correlação com resultado (W/L/D).
    # Filtra fatos descritivos puros (center_type, position_phase, castled)
    # que não trazem diagnóstico isolado.
    _PURE_DESCRIPTIVE = {"center_type", "position_phase", "castled", "opposite_side_castles"}
    facts_counter = Counter()
    facts_corr: dict[str, dict[str, int]] = {}
    # game_metrics será populado abaixo. Vamos popular depois numa segunda passada.
    # Conta temas só em lances do usuário com erro (loss_cp >= 50) — temas em
    # lances quietos do solver poluem o ranking. Confidence mínima 0.30 para
    # evitar fingerprints com classificação ambígua.
    tactical_top = []
    tactical_by_phase = {"abertura": [], "meio-jogo": [], "final": []}
    if "tactical_theme" in user_moves.columns:
        flagged = user_moves[(user_moves["loss_cp"] >= 50) & (user_moves["tactical_theme"] != "")]
        if len(flagged):
            try:
                conf_series = pd.to_numeric(flagged["tactical_confidence"], errors="coerce").fillna(0.0)
                flagged = flagged[conf_series >= 0.30]
            except Exception:
                pass
            theme_counter = Counter(flagged["tactical_theme"].tolist())
            tactical_top = [{"theme": t, "n": n} for t, n in theme_counter.most_common(5)]
            for ph in ["abertura", "meio-jogo", "final"]:
                sub = flagged[flagged["phase"] == ph]
                if len(sub):
                    pc = Counter(sub["tactical_theme"].tolist())
                    tactical_by_phase[ph] = [{"theme": t, "n": n} for t, n in pc.most_common(3)]

    # Por time_class (rapid/daily/blitz/bullet): KPIs separados + trio de scores.
    # Útil porque Daily (horas/lance, frequente uso de motor) infla; bullet deflaciona.
    # A separação por modalidade é o que isola o caso "score limpo em uma, suspeito em outra".
    by_time_class = {}
    opp_rating_per_game = pd.to_numeric(games_df.set_index("index")["opponent_rating"], errors="coerce") if "opponent_rating" in games_df.columns else None
    if "time_class" in games_df.columns:
        comp_window_for_tc = competitive_window(player_rating)
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
            if len(sub_m) and opp_rating_per_game is not None:
                opp_aligned = sub_m["game_index"].map(opp_rating_per_game)
                trio = compute_score_trio(
                    sub_m["loss_cp"], opp_aligned, depth, player_rating, comp_window_for_tc,
                    categories=sub_m["category"], results_per_move=sub_m["game_result"],
                )
            else:
                trio = compute_score_trio(
                    sub_m["loss_cp"] if len(sub_m) else pd.Series([], dtype=float),
                    pd.Series([], dtype=float), depth, player_rating, comp_window_for_tc,
                    categories=sub_m["category"] if len(sub_m) else None,
                    results_per_move=sub_m["game_result"] if len(sub_m) else None,
                )
            by_time_class[tc_str] = {
                "games": n,
                "games_relevant": n_rel,
                "wins": w, "losses": l, "draws": d,
                "win_rate": round(100 * w / n, 1) if n else 0,
                "acpl": trio["acpl_overall"] if trio["acpl_overall"] is not None else 0.0,
                "score_10": trio["score_10_overall"] if trio["score_10_overall"] is not None else 0.0,
                "score_10_competitive": trio["score_10_competitive"],
                "score_10_weighted": trio["score_10_weighted"],
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
            wr_c = round(100 * w / len(sub_g), 1)
            blunders_c = int((sub_m["category"] == "blunder").sum()) if len(sub_m) else 0
            by_color[color] = {
                "games": int(len(sub_g)),
                "games_relevant": n_rel,
                "wins": w, "losses": l, "draws": d,
                "win_rate": wr_c,
                "acpl": acpl_c,
                "accuracy": compute_accuracy(acpl_c),
                "score_10": compute_score10(acpl_c, depth, player_rating,
                                            win_rate=wr_c,
                                            blunders=blunders_c,
                                            n_user_moves=len(sub_m)),
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
        # ACPL e blunders por chave, vindos de user_moves (relevantes apenas)
        sub_user = user_moves_keyed.groupby(key_col)
        acpl_grp = sub_user["loss_cp"].mean().round(2).to_dict()
        blunders_grp = sub_user["category"].apply(lambda s: int((s == "blunder").sum())).to_dict()
        nmoves_grp = sub_user.size().to_dict()
        for key, sub in games_df.groupby(key_col):
            n = len(sub)
            w = int((sub["result"] == "Win").sum())
            l = int((sub["result"] == "Loss").sum())
            d = int((sub["result"] == "Draw").sum())
            n_rel = int(sub["index"].isin(relevant_game_indices).sum())
            wr_key = round(100 * w / n, 1) if n else 0
            ply_series = pd.to_numeric(sub.get("eco_ply"), errors="coerce") if "eco_ply" in sub.columns else pd.Series([], dtype=float)
            ply_clean = ply_series.dropna() if len(ply_series) else ply_series
            avg_ply = round(float(ply_clean.mean()), 1) if len(ply_clean) else None
            acpl_val = acpl_grp.get(key)
            out[key] = {
                "name": key, "n": n, "n_relevant": n_rel,
                "wins": w, "losses": l, "draws": d,
                "win_rate": wr_key,
                "acpl": acpl_val,
                "score_10": compute_score10(
                    acpl_val, depth, player_rating,
                    win_rate=wr_key,
                    blunders=blunders_grp.get(key),
                    n_user_moves=nmoves_grp.get(key),
                ) if acpl_val is not None else None,
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
        try:
            worst_facts = detect_position_facts(str(worst["fen_before"]))
        except Exception:
            worst_facts = []
        # Win-rate da partida individual: 100 (vitória), 0 (derrota), 50 (empate)
        result_g = meta.get("result")
        wr_g = 100.0 if result_g == "Win" else (0.0 if result_g == "Loss" else 50.0)
        blunders_g = int((user_sub["category"] == "blunder").sum())
        n_moves_g = int(len(user_sub))
        game_metrics.append({
            "game_index": int(gi),
            "result": result_g,
            "color": meta.get("color"),
            "opponent": meta.get("opponent"),
            "opponent_rating": safe_int(meta.get("opponent_rating")),
            "date": meta.get("date"),
            "url": meta.get("url"),
            "time_class": meta.get("time_class"),
            "termination": (meta.get("termination") or "").strip(),
            "acpl": acpl_g,
            "accuracy": compute_accuracy(acpl_g),
            "score_10": compute_score10(acpl_g, depth, player_rating,
                                        win_rate=wr_g, blunders=blunders_g,
                                        n_user_moves=n_moves_g),
            "n_user_moves": n_moves_g,
            "blunders": blunders_g,
            "mistakes": int((user_sub["category"] == "mistake").sum()),
            "worst_move": {
                "ply": int(worst["ply"]),
                "san": worst["move_san"],
                "best": worst["best_move"],
                "loss_cp": round(float(worst["loss_cp"]), 1),
                "fen_before": worst["fen_before"],
            },
            "worst_position_facts": worst_facts,
        })

    # Popula agregados de fatos estruturais com TODOS os lances flagrados
    # (loss_cp >= 50): muito mais sinal estatístico que apenas worst_move.
    # Por partida, cada `key` (kind+color) conta UMA vez (mesmo se aparece em
    # múltiplos lances) — evita inflar contagem em jogos longos.
    flagged_with_facts = user_moves[user_moves["loss_cp"] >= 50]
    result_by_game = {gm["game_index"]: gm.get("result") for gm in game_metrics}
    seen_per_game: dict[int, set[str]] = {}
    for _, mv in flagged_with_facts.iterrows():
        gi = mv["game_index"]
        facts_in_move = mv.get("position_facts") or []
        if not isinstance(facts_in_move, list):
            continue
        seen = seen_per_game.setdefault(int(gi), set())
        result = result_by_game.get(int(gi))
        for fact in facts_in_move:
            kind = fact.get("kind") if isinstance(fact, dict) else None
            if not kind or kind in _PURE_DESCRIPTIVE:
                continue
            color = fact.get("color")
            key = f"{kind}:{color}" if color else kind
            if key in seen:
                continue
            seen.add(key)
            facts_counter[key] += 1
            if result in ("Win", "Loss", "Draw"):
                facts_corr.setdefault(key, {"win": 0, "loss": 0, "draw": 0})
                facts_corr[key][result.lower()] += 1

    position_facts_top = [
        {"key": k, "n": n,
         "win_rate_when_present": (
             round(100 * facts_corr.get(k, {}).get("win", 0)
                   / max(1, sum(facts_corr.get(k, {}).values())), 1)
             if facts_corr.get(k) else None
         )}
        for k, n in facts_counter.most_common(15) if n >= 3
    ]

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

    OPENING_SKIP_PLIES = 8   # ignora livro de abertura na busca de lances decisivos
    SPREAD_MIN_PLIES = 8     # distância mínima entre os 2 lances "destacados" (anti-cascata)
    USER_HIGHLIGHT_MIN_SWING = 50  # swing mínimo a favor do jogador para aceitar como "melhor"

    def _entry_from_row(r):
        """Converte linha de moves_df em dict canônico do key_position."""
        theme = r.get("tactical_theme") or ""
        try:
            conf = float(r.get("tactical_confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        # position_facts pode vir como lista (computado in-flight) ou JSON string (cache do DB)
        pf = r.get("position_facts")
        if isinstance(pf, str) and pf:
            try: pf = json.loads(pf)
            except Exception: pf = []
        elif not isinstance(pf, list):
            pf = []
        entry = {
            "ply": int(r["ply"]),
            "phase": r["phase"],
            "side_to_move": r["side_to_move"],
            "is_user_move": bool(r["is_user_move"]),
            "san": r["move_san"],
            "best": r["best_move"],
            "loss_cp": round(float(r["loss_cp"]), 1),
            "swing_cp": round(float(r.get("swing_user") or 0), 1),
            "fen_before": r["fen_before"],
            "position_facts": pf,
        }
        if theme and conf >= 0.30:
            entry["tactical_theme"] = str(theme)
            entry["tactical_confidence"] = round(conf, 2)
            entry["tactical_source"] = str(r.get("tactical_source") or "")
        return entry

    def _pick_with_spread(df, sort_col, ascending=False, k=2, used_plies=None):
        """Pega top-k linhas espalhadas por ≥ SPREAD_MIN_PLIES e disjuntas de used_plies.
        Se spread não comportar k lances, relaxa o filtro mantendo unicidade."""
        used = set(used_plies or [])
        if len(df) == 0:
            return []
        sorted_df = df.sort_values(sort_col, ascending=ascending)
        chosen: list[dict] = []
        for _, row in sorted_df.iterrows():
            ply = int(row["ply"])
            if ply in used:
                continue
            if all(abs(ply - c["ply"]) >= SPREAD_MIN_PLIES for c in chosen):
                chosen.append(row.to_dict())
                if len(chosen) >= k:
                    return chosen
        # relaxa spread: completa com mais top-k mantendo só unicidade
        for _, row in sorted_df.iterrows():
            ply = int(row["ply"])
            if ply in used or any(c["ply"] == ply for c in chosen):
                continue
            chosen.append(row.to_dict())
            if len(chosen) >= k:
                break
        return chosen

    def _decisive_positions(game_index, user_color, result, n=3):
        """Vitória: 2 melhores lances do jogador (maior swing a favor) + 1 pior (maior loss).
        Derrota: 2 piores lances do jogador (maior loss) + 1 melhor lance do adversário
        (maior swing a favor do adversário). Spread mín. 8 plies entre os 2 destacados.
        Vitória "fácil" (nenhum lance do jogador com swing ≥50): fallback ao top-swings antigo.
        Saída sempre em ordem cronológica."""
        g = moves_df[(moves_df["game_index"] == game_index) & (moves_df["ply"] > OPENING_SKIP_PLIES)].copy()
        if len(g) == 0:
            g = moves_df[moves_df["game_index"] == game_index].copy()
        if len(g) == 0:
            return []

        user_is_white = (user_color == "White")
        user_won = (result == "Win")
        # swing_user: cp_after - cp_before normalizado pra "ganho do JOGADOR"
        sign = 1 if user_is_white else -1
        g["swing_user"] = (g["cp_after"] - g["cp_before"]) * sign

        user_moves = g[g["is_user_move"] == True]
        opp_moves = g[g["is_user_move"] == False]

        selected: list[dict] = []
        if user_won:
            # 2 melhores do jogador (maior swing positivo) com filtro de qualidade
            user_winning = user_moves[user_moves["swing_user"] >= USER_HIGHLIGHT_MIN_SWING]
            best_two = _pick_with_spread(user_winning, "swing_user", ascending=False, k=2)
            selected.extend(best_two)
            # 1 pior lance do jogador (maior loss_cp) — não precisa spread, mas sem duplicar
            if len(user_moves):
                used_plies = {c["ply"] for c in selected}
                worst_one = _pick_with_spread(user_moves, "loss_cp", ascending=False,
                                              k=1, used_plies=used_plies)
                selected.extend(worst_one)
            # Fallback "vitória fácil": jogador não teve highlight com swing ≥50.
            # Cai no critério antigo (top swings overall, qualquer autor).
            if len(selected) < 2:
                top = g.nlargest(n, "swing_user")
                selected = [r.to_dict() for _, r in top.iterrows()]
        else:
            # Derrota (ou empate). 2 piores do jogador.
            worst_two = _pick_with_spread(user_moves, "loss_cp", ascending=False, k=2)
            selected.extend(worst_two)
            # 1 melhor do adversário: maior swing CONTRA o jogador = -swing_user maximizado
            if len(opp_moves):
                opp_view = opp_moves.assign(swing_opp=-opp_moves["swing_user"])
                used_plies = {c["ply"] for c in selected}
                best_opp = _pick_with_spread(opp_view, "swing_opp", ascending=False,
                                             k=1, used_plies=used_plies)
                selected.extend(best_opp)
            if len(selected) < 2:
                top = g.nlargest(n, "loss_cp")
                selected = [r.to_dict() for _, r in top.iterrows()]

        # Garantia visual: se ficou abaixo de n (partida curta ou highlights raros),
        # completa com top swings/losses absolutos da partida sem duplicar plies.
        if len(selected) < n:
            used_plies = {int(c["ply"]) for c in selected}
            sort_col = "swing_user" if user_won else "loss_cp"
            extras = g.sort_values(sort_col, ascending=False)
            for _, row in extras.iterrows():
                if int(row["ply"]) in used_plies:
                    continue
                selected.append(row.to_dict())
                used_plies.add(int(row["ply"]))
                if len(selected) >= n:
                    break

        selected = selected[:n]
        selected.sort(key=lambda r: int(r["ply"]))
        return [_entry_from_row(r) for r in selected]

    for pg in paradigmatic:
        pg["key_positions"] = _decisive_positions(pg["game_index"], pg["color"], pg["result"])
        # Fatos estruturais do meio do jogo (key_positions já trazem facts via _entry_from_row,
        # com cache do DB ou fallback a detect_position_facts in-flight).
        pg_moves = moves_df[moves_df["game_index"] == pg["game_index"]].sort_values("ply").reset_index(drop=True)
        pg["position_facts"] = []
        if len(pg_moves):
            mid_idx = min(len(pg_moves) - 1, max(0, len(pg_moves) // 2))
            pg["position_facts"] = detect_position_facts(str(pg_moves.iloc[mid_idx]["fen_before"]))
        # Garante que key_positions sem facts no cache rodem in-flight aqui.
        for kp in pg["key_positions"]:
            if not kp.get("position_facts"):
                try:
                    kp["position_facts"] = detect_position_facts(str(kp["fen_before"]))
                except Exception:
                    kp["position_facts"] = []

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
    # ── Score por modalidade: média + spread (antes dos warnings) ──────
    # Para cada time_class com ≥10 partidas relevantes, pega o competitivo (ou geral se sem comp).
    # Média aritmética simples = trata cada formato como categoria independente, sem viés de
    # contagem de partidas. Spread (max-min) é diagnóstico: spread >2 indica modalidade fraudada
    # (Daily com motor) ou colapso por pressão de tempo (bullet).
    modality_scores = {}
    MIN_GAMES_PER_MODALITY = 10
    for tc, tc_data in by_time_class.items():
        if tc_data["games_relevant"] >= MIN_GAMES_PER_MODALITY:
            s_pref = tc_data.get("score_10_competitive")
            if s_pref is None:
                s_pref = tc_data.get("score_10")
            if s_pref is not None:
                modality_scores[tc] = s_pref
    if len(modality_scores) >= 2:
        score_modality_avg = round(sum(modality_scores.values()) / len(modality_scores), 1)
        score_modality_spread = round(max(modality_scores.values()) - min(modality_scores.values()), 1)
    elif len(modality_scores) == 1:
        score_modality_avg = list(modality_scores.values())[0]
        score_modality_spread = 0.0
    else:
        score_modality_avg = None
        score_modality_spread = None
    uncertainty_band = score_uncertainty_band(depth)

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
    # Sinal de uso de assistência externa: ACPL competitivo extremamente baixo é
    # implausível para humano (top GMs em torneios clássicos fazem ~15-25 cp).
    # Em Daily/correspondence o jogador costuma usar motor, o que infla o score.
    if competitive_acpl is not None and competitive_acpl < 15 and n_competitive >= 30:
        sample_warnings.append(
            f"ACPL competitivo de {competitive_acpl} cp em {n_competitive} partidas é implausível para jogo humano — possível uso de motor em algum formato (ex: Daily). Considere recoletar excluindo Daily/correspondência."
        )
    if score_modality_spread is not None and score_modality_spread >= 2.0 and len(modality_scores) >= 2:
        breakdown_str = ", ".join(f"{tc}={s}" for tc, s in modality_scores.items())
        sample_warnings.append(
            f"Spread de Score entre modalidades = {score_modality_spread} pontos ({breakdown_str}) — diferença grande sinaliza modalidades com regimes de jogo distintos (ex: Daily com motor vs Blitz humano). Use a média por modalidade no texto, e separe a discussão por formato."
        )
    if n_competitive < 10 and n_relevant >= 20:
        sample_warnings.append(
            f"Apenas {n_competitive} partidas contra adversários em ±{comp_window} Elo — Score competitivo tem amostra pequena; o relatório pode usar Score geral com a ressalva de viés por nível de adversário."
        )

    confidence_pct = compute_confidence_pct(n_relevant, depth, eco_coverage)

    # Calibração de score (transparência): mostra como score foi derivado de ACPL+depth+rating
    df_eq = depth_factor(depth)
    exp_acpl = round(expected_acpl(player_rating), 1)
    acpl_d20_eq = round(overall_acpl / df_eq, 2) if df_eq > 0 else overall_acpl
    perf_ratio = round(acpl_d20_eq / exp_acpl, 2) if exp_acpl > 0 else None
    competitive_pct = round(100 * n_competitive / n_relevant, 1) if n_relevant else 0.0

    score_calibration = {
        "player_rating": player_rating,
        "rating_basis": rating_basis,
        "depth": depth,
        "depth_factor": round(df_eq, 2),
        "acpl_observed": overall_acpl,
        "acpl_d20_equivalent": acpl_d20_eq,
        "expected_acpl_for_rating": exp_acpl,
        "performance_ratio": perf_ratio,
        "competitive_window_elo": comp_window,
        "n_competitive_games": n_competitive,
        "competitive_pct_of_relevant": competitive_pct,
        "competitive_acpl": competitive_acpl,
        "competitive_score_10": competitive_score,
        "weighted_sigma_elo": int(WEIGHT_SIGMA),
        "weighted_n_eff_games": n_eff_weighted,
        "weighted_acpl": weighted_acpl,
        "weighted_score_10": weighted_score,
    }

    puzzle_program = derive_puzzle_program(
        games_df=games_df,
        by_phase=by_phase,
        kpis={"blunders": cat_counts.get("blunder", 0), "mistakes": cat_counts.get("mistake", 0)},
        head_to_head=head_to_head,
        time_classes=time_classes,
    )

    # ── Score canônico (kpis.score_10) — Opção B: competitivo como base ──
    # Hierarquia: competitivo (n≥15) > média modalidade (≥2 mods, ≥10 cada)
    # > geral. Anota score_10_basis pra transparência: o redator e auditor
    # sabem qual variante o número canônico está representando.
    overall_score = compute_score10(overall_acpl, depth, player_rating,
                                    win_rate=overall_win_rate_moves,
                                    blunders=overall_blunders,
                                    n_user_moves=overall_n_moves)
    if competitive_score is not None and n_competitive >= 15:
        canonical_score = competitive_score
        canonical_basis = f"competitive (n={n_competitive}, ±{comp_window} Elo)"
    elif score_modality_avg is not None and len(modality_scores) >= 2:
        canonical_score = score_modality_avg
        canonical_basis = f"modality_avg ({len(modality_scores)} formatos)"
    else:
        canonical_score = overall_score
        canonical_basis = "overall (fallback — amostra competitiva insuficiente)"

    payload = {
        "username": username,
        "stamp": stamp,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_games_csv": games_path.name if games_path else "history.db:games",
        "source_analysis_csv": analysis_path.name if analysis_path else "history.db:game_analyses",
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
            "score_10": canonical_score,
            "score_10_basis": canonical_basis,
            "score_10_competitive": competitive_score,
            "score_10_weighted": weighted_score,
            "score_10_overall": overall_score,
            "score_10_by_modality_avg": score_modality_avg,
            "score_10_modality_spread": score_modality_spread,
            "score_10_by_modality_breakdown": modality_scores,
            "score_uncertainty_band": uncertainty_band,
            "n_competitive_games": n_competitive,
            "competitive_window_elo": comp_window,
            "weighted_n_eff_games": n_eff_weighted,
            "blunders": cat_counts.get("blunder", 0),
            "mistakes": cat_counts.get("mistake", 0),
            "inaccuracies": cat_counts.get("inaccuracy", 0),
            "good_moves": cat_counts.get("good", 0),
            "tactical_themes_top": tactical_top,
            "tactical_themes_by_phase": tactical_by_phase,
            "position_facts_top": position_facts_top,
            "position_facts_correlation": facts_corr,
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

    # Persistência longitudinal (SQLite) + cache de position_facts.
    try:
        from history import open_db, record_analysis, update_position_facts_batch
        conn = open_db(DATA_DIR / "history.db")
        record_analysis(conn, payload, perspective=None)
        # Cache de position_facts: para cada lance flagrado cujo facts foi
        # computado in-flight, grava o JSON na coluna position_facts. Próxima
        # execução de compute --from-db lê direto, sem recomputar.
        if from_db:
            facts_to_cache = []
            for _, mv in moves_df.iterrows():
                if not mv.get("_facts_computed_now"):
                    continue
                gid = mv.get("game_id")
                if not gid:
                    continue
                facts_list = mv.get("position_facts") or []
                facts_to_cache.append((str(gid), int(mv["ply"]),
                                       json.dumps(facts_list, ensure_ascii=False)))
            if facts_to_cache:
                n = update_position_facts_batch(conn, facts_to_cache)
                print(f"   💾 position_facts cacheados: {n} lances")
        conn.close()
    except Exception as e:
        print(f"⚠ histórico não gravado: {e}")

    print(f"✅ {out_path}")
    print(f"   ACPL={overall_acpl} | accuracy={overall_accuracy}% | "
          f"W/L/D={wins}/{losses}/{draws} | partidas paradigmáticas={len(paradigmatic)}")
    print(f"   Score canônico: {canonical_score}/10 — base: {canonical_basis}")
    print(f"   Variantes: geral={overall_score} | competitivo={competitive_score} (n={n_competitive}, ±{comp_window} Elo) | "
          f"ponderado={weighted_score} (n_eff={n_eff_weighted}, σ={int(WEIGHT_SIGMA)} Elo)")
    if modality_scores:
        breakdown = " ".join(f"{tc}={s}" for tc, s in modality_scores.items())
        print(f"   Por modalidade: {breakdown} | média={score_modality_avg} | spread={score_modality_spread} | faixa-incerteza-depth=±{uncertainty_band}")


if __name__ == "__main__":
    main()

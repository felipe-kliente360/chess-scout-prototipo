"""Detectores estruturais determinísticos. Cada função recebe um chess.Board
e retorna lista de fatos (dicts) ou lista vazia. Sem interpretação, sem
peso, sem contexto — só geometria.

Os fatos alimentam o agregado `kpis.position_facts_top` no compute.py e as
narrativas de partidas paradigmáticas. O redator combina/interpreta os
fatos no texto.

Uso:
    from position_facts import detect_facts
    facts = detect_facts(fen)  # ou board
"""
from __future__ import annotations

import chess

PIECE_VALUE = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100,
}
SYM = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
       chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}
COLOR_NAME = {chess.WHITE: "w", chess.BLACK: "b"}
FILE_LETTER = "abcdefgh"


def _files_of_pawns(board: chess.Board):
    """Retorna (files_white, files_black) onde cada lista[0..7] = nº peões."""
    fw = [0] * 8
    fb = [0] * 8
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN:
            f = chess.square_file(sq)
            if p.color == chess.WHITE:
                fw[f] += 1
            else:
                fb[f] += 1
    return fw, fb


def _square_color(sq: int) -> str:
    """light ou dark."""
    return "light" if (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1 else "dark"


# ── Estrutura de peões ─────────────────────────────────────────────────

def detect_isolated_pawns(board):
    fw, fb = _files_of_pawns(board)
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.piece_type != chess.PAWN:
            continue
        f = chess.square_file(sq)
        files = fw if p.color == chess.WHITE else fb
        left = files[f - 1] if f > 0 else 0
        right = files[f + 1] if f < 7 else 0
        if left == 0 and right == 0:
            out.append({"kind": "isolated_pawn",
                        "color": COLOR_NAME[p.color],
                        "square": chess.square_name(sq)})
    return out


def detect_doubled_pawns(board):
    out = []
    for color in (chess.WHITE, chess.BLACK):
        files = [[] for _ in range(8)]
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.piece_type == chess.PAWN and p.color == color:
                files[chess.square_file(sq)].append(chess.square_name(sq))
        for col_pawns in files:
            if len(col_pawns) >= 2:
                out.append({"kind": "doubled_pawn",
                            "color": COLOR_NAME[color],
                            "squares": sorted(col_pawns)})
    return out


def detect_passed_pawns(board):
    fw, fb = _files_of_pawns(board)
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.piece_type != chess.PAWN:
            continue
        f = chess.square_file(sq)
        r = chess.square_rank(sq)
        # "à frente" depende da cor
        if p.color == chess.WHITE:
            ahead_ranks = range(r + 1, 8)
            enemy_files = fb
        else:
            ahead_ranks = range(0, r)
            enemy_files = fb if p.color == chess.WHITE else fw
            enemy_files = fw  # peão preto vê peões brancos
        # Confirma: se peão é preto, o adversário é branco
        enemy_files = fb if p.color == chess.WHITE else fw

        # Adversários nas colunas f, f-1, f+1, à frente
        blocked = False
        for ef in (f - 1, f, f + 1):
            if ef < 0 or ef > 7:
                continue
            # Tem peão adversário em alguma rank "à frente" desta coluna?
            for sq2 in chess.SQUARES:
                p2 = board.piece_at(sq2)
                if p2 and p2.piece_type == chess.PAWN and p2.color != p.color:
                    if chess.square_file(sq2) == ef and chess.square_rank(sq2) in ahead_ranks:
                        blocked = True
                        break
            if blocked:
                break
        if blocked:
            continue
        # Defendido por outro peão?
        protected = False
        own_pawn_attackers = board.attackers(p.color, sq)
        for atk_sq in own_pawn_attackers:
            atk = board.piece_at(atk_sq)
            if atk and atk.piece_type == chess.PAWN:
                protected = True
                break
        out.append({"kind": "passed_pawn",
                    "color": COLOR_NAME[p.color],
                    "square": chess.square_name(sq),
                    "protected": protected})
    return out


def detect_backward_pawns(board):
    """Peão atrás dos aliados nas colunas adjacentes E não pode avançar com
    segurança (casa à frente atacada por peão adversário sem defensor peão)."""
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.piece_type != chess.PAWN:
            continue
        f = chess.square_file(sq)
        r = chess.square_rank(sq)
        # Peões aliados nas colunas adjacentes na mesma rank ou à frente?
        # Para peão branco, "à frente" = ranks maiores. Se aliado adjacente
        # está em rank igual ou maior, este peão está atrás.
        is_white = p.color == chess.WHITE
        ally_adj_ahead_or_equal = False
        for af in (f - 1, f + 1):
            if af < 0 or af > 7:
                continue
            for sq2 in chess.SQUARES:
                p2 = board.piece_at(sq2)
                if not p2 or p2.piece_type != chess.PAWN or p2.color != p.color:
                    continue
                if chess.square_file(sq2) != af:
                    continue
                r2 = chess.square_rank(sq2)
                if (is_white and r2 >= r) or (not is_white and r2 <= r):
                    ally_adj_ahead_or_equal = True
                    break
            if ally_adj_ahead_or_equal:
                break
        if not ally_adj_ahead_or_equal:
            continue
        # Casa à frente: f, r+1 (white) ou r-1 (black)
        front_r = r + 1 if is_white else r - 1
        if not (0 <= front_r <= 7):
            continue
        front_sq = chess.square(f, front_r)
        # Peão adversário ataca essa casa? (attackers só de peões inimigos)
        enemy_pawn_attackers = []
        for asq in board.attackers(not p.color, front_sq):
            ap = board.piece_at(asq)
            if ap and ap.piece_type == chess.PAWN:
                enemy_pawn_attackers.append(asq)
        if not enemy_pawn_attackers:
            continue
        # Defensores peão aliado da casa à frente?
        own_pawn_defenders = []
        for dsq in board.attackers(p.color, front_sq):
            dp = board.piece_at(dsq)
            if dp and dp.piece_type == chess.PAWN:
                own_pawn_defenders.append(dsq)
        if own_pawn_defenders:
            continue  # avança com segurança
        out.append({"kind": "backward_pawn",
                    "color": COLOR_NAME[p.color],
                    "square": chess.square_name(sq)})
    return out


def detect_pawn_chains(board):
    """Cadeias de ≥3 peões da mesma cor em diagonal conectada."""
    out = []
    for color in (chess.WHITE, chess.BLACK):
        pawns = [sq for sq in chess.SQUARES
                 if (p := board.piece_at(sq)) and p.piece_type == chess.PAWN and p.color == color]
        # Direção da diagonal: peões se defendem se estão a (df=±1, dr=+1) para branco ou (df=±1, dr=-1) para preto
        dr = 1 if color == chess.WHITE else -1
        # Constrói grafo: aresta se peão A defende peão B
        defenders = {sq: [] for sq in pawns}
        for sq in pawns:
            f, r = chess.square_file(sq), chess.square_rank(sq)
            for df in (-1, 1):
                target = chess.square(f + df, r + dr) if 0 <= f + df <= 7 and 0 <= r + dr <= 7 else None
                if target in pawns:
                    defenders[target].append(sq)
        # Cadeia = caminho de defensores. Pega só cadeias maximais ≥3.
        seen = set()
        for sq in pawns:
            # tem defensor?
            chain = [sq]
            cur = sq
            while defenders.get(cur):
                cur = defenders[cur][0]  # pega um defensor
                if cur in chain:
                    break
                chain.append(cur)
            if len(chain) >= 3 and tuple(sorted(chain)) not in seen:
                seen.add(tuple(sorted(chain)))
                out.append({"kind": "pawn_chain",
                            "color": COLOR_NAME[color],
                            "squares": [chess.square_name(s) for s in sorted(chain, key=lambda x: chess.square_rank(x))],
                            "length": len(chain)})
    return out


def detect_pawn_majorities(board):
    fw, fb = _files_of_pawns(board)
    qs_w, qs_b = sum(fw[:4]), sum(fb[:4])
    ks_w, ks_b = sum(fw[4:]), sum(fb[4:])
    out = []
    if qs_w - qs_b >= 2:
        out.append({"kind": "pawn_majority", "color": "w", "side": "queenside", "count_diff": qs_w - qs_b})
    elif qs_b - qs_w >= 2:
        out.append({"kind": "pawn_majority", "color": "b", "side": "queenside", "count_diff": qs_b - qs_w})
    if ks_w - ks_b >= 2:
        out.append({"kind": "pawn_majority", "color": "w", "side": "kingside", "count_diff": ks_w - ks_b})
    elif ks_b - ks_w >= 2:
        out.append({"kind": "pawn_majority", "color": "b", "side": "kingside", "count_diff": ks_b - ks_w})
    return out


def detect_iqp(board):
    """Peão dama isolado: peão d sem c-peão e sem e-peão, na 4ª/5ª rank."""
    fw, fb = _files_of_pawns(board)
    out = []
    if fw[3] >= 1 and fw[2] == 0 and fw[4] == 0:
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.piece_type == chess.PAWN and p.color == chess.WHITE \
               and chess.square_file(sq) == 3 and chess.square_rank(sq) == 3:
                out.append({"kind": "iqp", "color": "w", "square": chess.square_name(sq)})
                break
    if fb[3] >= 1 and fb[2] == 0 and fb[4] == 0:
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.piece_type == chess.PAWN and p.color == chess.BLACK \
               and chess.square_file(sq) == 3 and chess.square_rank(sq) == 4:
                out.append({"kind": "iqp", "color": "b", "square": chess.square_name(sq)})
                break
    return out


def detect_hanging_pawns(board):
    """Par c+d (ou d+e) na 4ª rank sem peões adjacentes nas colunas vizinhas."""
    fw, fb = _files_of_pawns(board)
    out = []
    for color, files, rank in [(chess.WHITE, fw, 3), (chess.BLACK, fb, 4)]:
        # c+d sem b nem e
        if files[2] == 1 and files[3] == 1 and files[1] == 0 and files[4] == 0:
            sqs = []
            for sq in chess.SQUARES:
                p = board.piece_at(sq)
                if p and p.piece_type == chess.PAWN and p.color == color and chess.square_file(sq) in (2, 3):
                    sqs.append(chess.square_name(sq))
            if len(sqs) == 2:
                out.append({"kind": "hanging_pawns", "color": COLOR_NAME[color], "squares": sorted(sqs)})
    return out


# ── Controle de colunas e diagonais ─────────────────────────────────────

def detect_open_files(board):
    fw, fb = _files_of_pawns(board)
    out = []
    for f in range(8):
        if fw[f] == 0 and fb[f] == 0:
            rooks_w, rooks_b = [], []
            for r in range(8):
                sq = chess.square(f, r)
                p = board.piece_at(sq)
                if p and p.piece_type in (chess.ROOK, chess.QUEEN):
                    if p.color == chess.WHITE:
                        rooks_w.append(chess.square_name(sq))
                    else:
                        rooks_b.append(chess.square_name(sq))
            out.append({"kind": "open_file", "file": FILE_LETTER[f],
                        "rooks_white": rooks_w, "rooks_black": rooks_b})
    return out


def detect_semi_open_files(board):
    fw, fb = _files_of_pawns(board)
    out = []
    for f in range(8):
        if fw[f] == 0 and fb[f] > 0:
            out.append({"kind": "semi_open_file", "file": FILE_LETTER[f], "color": "w"})
        elif fb[f] == 0 and fw[f] > 0:
            out.append({"kind": "semi_open_file", "file": FILE_LETTER[f], "color": "b"})
    return out


def detect_seventh_rank(board):
    """Torre/dama na 7ª fila do adversário (rank 6 para branco, rank 1 para preto)."""
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.piece_type not in (chess.ROOK, chess.QUEEN):
            continue
        r = chess.square_rank(sq)
        if p.color == chess.WHITE and r == 6:
            out.append({"kind": "seventh_rank", "color": "w",
                        "piece": SYM[p.piece_type], "square": chess.square_name(sq)})
        elif p.color == chess.BLACK and r == 1:
            out.append({"kind": "seventh_rank", "color": "b",
                        "piece": SYM[p.piece_type], "square": chess.square_name(sq)})
    return out


def detect_long_diagonal_open(board):
    """Bispo na diagonal a1-h8 ou h1-a8 com diagonal sem obstrução."""
    out = []
    diagonals = [
        ("a1-h8", [chess.square(i, i) for i in range(8)]),
        ("h1-a8", [chess.square(7 - i, i) for i in range(8)]),
    ]
    for label, squares in diagonals:
        # Verifica se há bispo na diagonal e se o resto está livre (exceto outro bispo aliado)
        bishops_on = []
        non_bishop_pieces = []
        for sq in squares:
            p = board.piece_at(sq)
            if not p:
                continue
            if p.piece_type == chess.BISHOP:
                bishops_on.append((sq, p.color))
            else:
                non_bishop_pieces.append((sq, p))
        for bsq, bcolor in bishops_on:
            # Conta obstruções: peças que não sejam o próprio bispo
            obstructions = sum(1 for sq, p in non_bishop_pieces)
            if obstructions <= 1:  # diagonal essencialmente aberta
                out.append({"kind": "long_diagonal_open",
                            "diagonal": label,
                            "color": COLOR_NAME[bcolor],
                            "bishop": chess.square_name(bsq)})
    return out


def detect_bishop_quality(board):
    """Bom/mau bispo conforme nº de peões próprios na cor do bispo.
    Bispo bom: ≤2 peões próprios na sua cor. Mau: ≥4."""
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.piece_type != chess.BISHOP:
            continue
        bishop_color = _square_color(sq)
        own_pawns_on_color = 0
        for sq2 in chess.SQUARES:
            p2 = board.piece_at(sq2)
            if p2 and p2.piece_type == chess.PAWN and p2.color == p.color \
               and _square_color(sq2) == bishop_color:
                own_pawns_on_color += 1
        if own_pawns_on_color >= 4:
            out.append({"kind": "bad_bishop", "color": COLOR_NAME[p.color],
                        "square": chess.square_name(sq),
                        "color_complex": bishop_color,
                        "own_pawns_on_color": own_pawns_on_color})
        elif own_pawns_on_color <= 2:
            out.append({"kind": "good_bishop", "color": COLOR_NAME[p.color],
                        "square": chess.square_name(sq),
                        "color_complex": bishop_color,
                        "own_pawns_on_color": own_pawns_on_color})
    return out


# ── Segurança do rei ────────────────────────────────────────────────────

def detect_king_in_center(board):
    out = []
    n_pieces = chess.popcount(board.occupied)
    in_endgame = n_pieces <= 14  # poucas peças = final, rei no centro é normal
    for color in (chess.WHITE, chess.BLACK):
        ksq = board.king(color)
        if ksq is None:
            continue
        f = chess.square_file(ksq)
        if f in (3, 4) and not in_endgame:
            # Perdeu direito de roque?
            cr_kingside = board.has_kingside_castling_rights(color)
            cr_queenside = board.has_queenside_castling_rights(color)
            if not (cr_kingside or cr_queenside):
                out.append({"kind": "king_in_center", "color": COLOR_NAME[color],
                            "square": chess.square_name(ksq),
                            "n_pieces": n_pieces})
    return out


def _shield_files(king_file: int) -> list[int]:
    if king_file >= 5:  # kingside
        return [5, 6, 7]
    if king_file <= 2:  # queenside
        return [0, 1, 2]
    return []


def detect_pawn_shield(board):
    """Para cada rei rocado, escudo de 3 peões: intacto, parcial ou ausente."""
    out = []
    for color in (chess.WHITE, chess.BLACK):
        ksq = board.king(color)
        if ksq is None:
            continue
        kf = chess.square_file(ksq)
        side = "kingside" if kf >= 5 else ("queenside" if kf <= 2 else None)
        if side is None:
            continue  # rei no centro, outro detector cuida
        files = _shield_files(kf)
        # Linha original do escudo: rank 1 (white) ou rank 6 (black)
        shield_rank = 1 if color == chess.WHITE else 6
        intact_count = 0
        missing_files = []
        for f in files:
            sq = chess.square(f, shield_rank)
            p = board.piece_at(sq)
            if p and p.piece_type == chess.PAWN and p.color == color:
                intact_count += 1
            else:
                missing_files.append(FILE_LETTER[f])
        if intact_count == 3:
            out.append({"kind": "pawn_shield_intact",
                        "color": COLOR_NAME[color], "side": side})
        elif intact_count == 0:
            out.append({"kind": "pawn_shield_absent",
                        "color": COLOR_NAME[color], "side": side,
                        "missing_files": missing_files})
        else:
            out.append({"kind": "pawn_shield_broken",
                        "color": COLOR_NAME[color], "side": side,
                        "missing_files": missing_files,
                        "remaining": intact_count})
    return out


def detect_open_file_near_king(board):
    fw, fb = _files_of_pawns(board)
    out = []
    for color in (chess.WHITE, chess.BLACK):
        ksq = board.king(color)
        if ksq is None:
            continue
        kf = chess.square_file(ksq)
        for f in range(max(0, kf - 1), min(8, kf + 2)):
            if fw[f] == 0 and fb[f] == 0:
                out.append({"kind": "open_file_near_king",
                            "color": COLOR_NAME[color],
                            "file": FILE_LETTER[f],
                            "distance": abs(f - kf)})
    return out


# ── Material e peças ────────────────────────────────────────────────────

def detect_bishop_pair(board):
    out = []
    for color in (chess.WHITE, chess.BLACK):
        bishops = [sq for sq in chess.SQUARES
                   if (p := board.piece_at(sq)) and p.piece_type == chess.BISHOP and p.color == color]
        if len(bishops) == 2:
            colors = {_square_color(b) for b in bishops}
            if len(colors) == 2:  # cores opostas
                out.append({"kind": "bishop_pair", "color": COLOR_NAME[color]})
    return out


def detect_opposite_color_bishops(board):
    bishops_w = [sq for sq in chess.SQUARES
                 if (p := board.piece_at(sq)) and p.piece_type == chess.BISHOP and p.color == chess.WHITE]
    bishops_b = [sq for sq in chess.SQUARES
                 if (p := board.piece_at(sq)) and p.piece_type == chess.BISHOP and p.color == chess.BLACK]
    if len(bishops_w) == 1 and len(bishops_b) == 1:
        if _square_color(bishops_w[0]) != _square_color(bishops_b[0]):
            return [{"kind": "opposite_color_bishops"}]
    return []


def detect_piece_mobility_extremes(board):
    """Reporta peças menores com mobilidade extrema (≤2 ou ≥7).
    Mobilidade = nº de casas atacadas pela peça (cada cor avaliada
    independente de quem é a vez)."""
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.piece_type not in (chess.KNIGHT, chess.BISHOP):
            continue
        attacks = board.attacks(sq)
        n = chess.popcount(int(attacks))
        if n <= 2:
            out.append({"kind": "piece_low_mobility",
                        "color": COLOR_NAME[p.color],
                        "piece": SYM[p.piece_type],
                        "square": chess.square_name(sq),
                        "squares_attacked": n})
        elif n >= 7:
            out.append({"kind": "piece_high_mobility",
                        "color": COLOR_NAME[p.color],
                        "piece": SYM[p.piece_type],
                        "square": chess.square_name(sq),
                        "squares_attacked": n})
    return out


def detect_static_trapped_piece(board):
    """Peça (qualquer ≥B) sem casas legais OU com todas as fugas em casa
    atacada por peça de menor valor sem ser defendida."""
    out = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p or p.piece_type in (chess.PAWN, chess.KING):
            continue
        # Movimentos pseudo-legais a partir desta casa (sem checar xeque do próprio rei)
        own_attacks = board.attacks(sq)
        legal_squares = []
        for to_sq in chess.SQUARES:
            if not own_attacks & chess.BB_SQUARES[to_sq]:
                continue
            target = board.piece_at(to_sq)
            if target and target.color == p.color:
                continue
            # Casa atacada por adversário com valor menor?
            attackers = board.attackers(not p.color, to_sq)
            min_attacker_value = min(
                (PIECE_VALUE[board.piece_at(asq).piece_type]
                 for asq in attackers if board.piece_at(asq)),
                default=999
            )
            if min_attacker_value < PIECE_VALUE[p.piece_type]:
                # Casa de risco — só é fuga se for defendida com valor ≤ atacante
                defenders = board.attackers(p.color, to_sq)
                min_defender = min(
                    (PIECE_VALUE[board.piece_at(dsq).piece_type]
                     for dsq in defenders if board.piece_at(dsq)),
                    default=999
                )
                if min_defender > min_attacker_value:
                    continue  # casa perdedora
            legal_squares.append(to_sq)
        if not legal_squares:
            out.append({"kind": "static_trapped_piece",
                        "color": COLOR_NAME[p.color],
                        "piece": SYM[p.piece_type],
                        "square": chess.square_name(sq)})
    return out


# ── Caráter da posição ─────────────────────────────────────────────────

def detect_center_type(board):
    central_pawns = 0
    for sq in (chess.D4, chess.D5, chess.E4, chess.E5):
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN:
            central_pawns += 1
    locked = False
    for f, rw, rb in [(3, 3, 4), (4, 3, 4)]:
        wp = board.piece_at(chess.square(f, rw))
        bp = board.piece_at(chess.square(f, rb))
        if wp and wp.piece_type == chess.PAWN and wp.color == chess.WHITE \
           and bp and bp.piece_type == chess.PAWN and bp.color == chess.BLACK:
            locked = True
            break
    if locked:
        value = "closed"
    elif central_pawns == 0:
        value = "open"
    elif central_pawns <= 2:
        value = "semi_open"
    else:
        value = "mixed"
    return [{"kind": "center_type", "value": value}]


def detect_position_phase(board):
    n_pieces = chess.popcount(board.occupied)
    fullmove = board.fullmove_number
    if fullmove <= 10:
        phase = "opening"
    elif n_pieces <= 14:
        phase = "endgame"
    else:
        phase = "middlegame"
    return [{"kind": "position_phase", "value": phase, "n_pieces": n_pieces}]


def detect_castling_state(board):
    """Estado de roque dos dois reis: kingside, queenside, ou center."""
    out = []
    for color in (chess.WHITE, chess.BLACK):
        ksq = board.king(color)
        if ksq is None:
            continue
        kf = chess.square_file(ksq)
        rank = chess.square_rank(ksq)
        # Considera "rocou" se rei está fora da casa central E na fileira de origem
        home_rank = 0 if color == chess.WHITE else 7
        if rank == home_rank:
            if kf >= 5:
                out.append({"kind": "castled", "color": COLOR_NAME[color], "side": "kingside"})
            elif kf <= 2:
                out.append({"kind": "castled", "color": COLOR_NAME[color], "side": "queenside"})
    if len(out) == 2:
        sides = {f["side"] for f in out}
        if len(sides) == 2:
            out.append({"kind": "opposite_side_castles"})
    return out


# ── Novos detectores táticos ──────────────────────────────────────────

def detect_overloaded_pieces(board: chess.Board) -> list[dict]:
    """Peça adversária (do ponto de vista de quem está a jogar) que defende
    simultaneamente 2+ peças valiosas (valor >= cavalo), ambas atacadas.
    Clássico motivo de sobrecarga — base para deflection e capturing-defender."""
    us = board.turn
    them = not us
    out = []

    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece or piece.color != them:
            continue
        # Peças aliadas que este defensor cobre (está nos seus attackers)
        defended = [
            s for s in chess.SQUARES
            if board.piece_at(s) and board.piece_at(s).color == them
            and s != sq
            and sq in board.attackers(them, s)
        ]
        # Das defendidas, quais estão sob ataque nosso E têm valor >= cavalo?
        threatened = [
            s for s in defended
            if board.is_attacked_by(us, s)
            and PIECE_VALUE.get(board.piece_at(s).piece_type, 0) >= 3
        ]
        if len(threatened) >= 2:
            out.append({
                "kind":      "overloaded_piece",
                "color":     COLOR_NAME[them],
                "piece":     SYM[piece.piece_type],
                "square":    chess.square_name(sq),
                "defending": [chess.square_name(s) for s in threatened],
            })
    return out


def detect_exposed_king(board: chess.Board) -> list[dict]:
    """Rei sem escudo de peões E coluna do rei aberta ou semi-aberta.
    Só detecta no meio-jogo (n_pieces > 10) para evitar falsos em finais."""
    n_pieces = chess.popcount(board.occupied)
    if n_pieces <= 10:
        return []
    fw, fb = _files_of_pawns(board)
    out = []
    for color in (chess.WHITE, chess.BLACK):
        ksq = board.king(color)
        if ksq is None:
            continue
        kf = chess.square_file(ksq)
        kr = chess.square_rank(ksq)
        own_files = fw if color == chess.WHITE else fb
        # Peões do próprio lado na coluna do rei e vizinhas
        shield = sum(own_files[f] for f in range(max(0, kf - 1), min(8, kf + 2)))
        if shield > 0:
            continue  # há pelo menos um peão de escudo
        # Coluna do rei: aberta (sem peões de nenhum lado)?
        enemy_files = fb if color == chess.WHITE else fw
        col_open = own_files[kf] == 0 and enemy_files[kf] == 0
        if not col_open:
            continue
        out.append({
            "kind":        "exposed_king",
            "color":       COLOR_NAME[color],
            "square":      chess.square_name(ksq),
            "shield_pawns": shield,
            "file_open":   True,
        })
    return out


def detect_pin_family(board: chess.Board) -> list[dict]:
    """Detecta peças cravadas (pin) com dois subtipos:
    - pin_prevents_attack: peça cravada ataca alvo valioso mas não pode capturar
    - pin_prevents_escape: peça cravada de alto valor sem casas seguras na ray do pin

    Só peças de HIGH_VALUE (≥ cavalo) são relatadas para evitar ruído de peões cravados.
    """
    HIGH_VALUE = {chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN}
    out = []

    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for sq in chess.SquareSet(board.occupied_co[color]):
            piece = board.piece_at(sq)
            if piece is None or piece.piece_type not in HIGH_VALUE:
                continue
            if not board.is_pinned(color, sq):
                continue

            pin_ray = board.pin(color, sq)  # SquareSet of squares the piece may move to

            # Subtype A: pin_prevents_attack
            # Peça cravada ataca pelo menos uma peça inimiga de alto valor,
            # mas o alvo não está na ray do pin (logo a captura é ilegal).
            attacks_val_targets = False
            for target_sq in board.attacks(sq):
                target = board.piece_at(target_sq)
                if (target and target.color == enemy
                        and target.piece_type in HIGH_VALUE
                        and target_sq not in pin_ray):
                    attacks_val_targets = True
                    break

            if attacks_val_targets:
                out.append({
                    "kind":     "pin_prevents_attack",
                    "subtype":  "pin",
                    "color":    COLOR_NAME[color],
                    "piece":    SYM[piece.piece_type],
                    "square":   chess.square_name(sq),
                })
                continue  # não duplicar com prevents_escape na mesma peça

            # Subtype B: pin_prevents_escape
            # Peça de alto valor cravada com zero casas seguras na ray do pin.
            legal_in_ray = 0
            for to_sq in pin_ray:
                if to_sq == sq:
                    continue
                target = board.piece_at(to_sq)
                if target and target.color == color:
                    continue  # bloqueada por peça própria
                # simples: se está na ray o lance pode ser legal (checagem fina é cara)
                legal_in_ray += 1

            if legal_in_ray == 0 and PIECE_VALUE.get(piece.piece_type, 0) >= 3:
                out.append({
                    "kind":    "pin_prevents_escape",
                    "subtype": "pin",
                    "color":   COLOR_NAME[color],
                    "piece":   SYM[piece.piece_type],
                    "square":  chess.square_name(sq),
                })

    return out


# ── Registro central ───────────────────────────────────────────────────

ALL_DETECTORS = [
    # estrutura
    detect_isolated_pawns,
    detect_doubled_pawns,
    detect_passed_pawns,
    detect_backward_pawns,
    detect_pawn_chains,
    detect_pawn_majorities,
    detect_iqp,
    detect_hanging_pawns,
    # colunas/diagonais
    detect_open_files,
    detect_semi_open_files,
    detect_seventh_rank,
    detect_long_diagonal_open,
    detect_bishop_quality,
    # rei
    detect_king_in_center,
    detect_pawn_shield,
    detect_open_file_near_king,
    # peças
    detect_bishop_pair,
    detect_opposite_color_bishops,
    detect_piece_mobility_extremes,
    detect_static_trapped_piece,
    detect_overloaded_pieces,
    detect_exposed_king,
    detect_pin_family,
    # caráter
    detect_center_type,
    detect_position_phase,
    detect_castling_state,
]


# Detectores que só fazem sentido depois do livro de abertura (peças iniciais
# bloqueadas pelos próprios peões geram ruído em ply ≤ 8). Suprimimos esses
# fatos quando fullmove_number ≤ 8.
_OPENING_NOISE_KINDS = {
    "bad_bishop", "good_bishop",
    "piece_low_mobility", "piece_high_mobility",
    "static_trapped_piece",
}
# Detectores ruidosos em finais com ≤6 peças (open_file aparece em quase tudo).
_ENDGAME_NOISE_KINDS = {"open_file_near_king"}


def detect_facts(fen_or_board) -> list[dict]:
    """Roda todos os detectores. Aceita FEN string ou chess.Board."""
    if isinstance(fen_or_board, chess.Board):
        board = fen_or_board
    else:
        try:
            board = chess.Board(str(fen_or_board))
        except Exception:
            return []
    facts = []
    for det in ALL_DETECTORS:
        try:
            result = det(board)
            if result:
                facts.extend(result)
        except Exception:
            continue
    fullmove = board.fullmove_number
    n_pieces = chess.popcount(board.occupied)
    if fullmove <= 8:
        facts = [f for f in facts if f["kind"] not in _OPENING_NOISE_KINDS]
    if n_pieces <= 6:
        facts = [f for f in facts if f["kind"] not in _ENDGAME_NOISE_KINDS]
    return facts


def fact_keys(facts: list[dict]) -> list[str]:
    """Converte fatos para chaves canônicas curtas (ex: 'isolated_pawn:w:d4').
    Útil pra agregação por contagem em todas as partidas."""
    out = []
    for f in facts:
        k = f["kind"]
        parts = [k]
        for field in ("color", "value", "side", "file", "square", "diagonal", "piece"):
            if field in f:
                parts.append(str(f[field]))
        out.append(":".join(parts))
    return out

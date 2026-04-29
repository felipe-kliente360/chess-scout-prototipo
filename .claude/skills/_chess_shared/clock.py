"""Extração de tempo por lance a partir de PGN com anotação `[%clk H:MM:SS.s]`.

Chess.com grava `%clk` após cada lance (já incluindo o increment).
time_control vem em segundos: "600" (10min, sem incr.), "180+2" (3+2),
"1/86400" (daily — 1 lance por dia, ignorar).

Funções públicas:
  parse_time_control(tc)         → (base_ms, increment_ms) ou None se daily
  extract_clocks(pgn, tc)        → list[dict(ply, clock_ms, time_spent_ms)]
  is_daily(tc)                   → bool
"""
from __future__ import annotations

import re

_CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)\]")
_MOVE_BLOCK_RE = re.compile(
    r"(\d+)(\.{1,3})\s*([^\s{]+)\s*(?:\{([^}]*)\})?"
)


def parse_time_control(tc) -> tuple[int, int] | None:
    """(base_ms, increment_ms) ou None se daily/inválido.
    Aceita: "600", "180+2", "1/86400" (daily, retorna None)."""
    if tc is None:
        return None
    s = str(tc).strip()
    if not s or s == "-" or "/" in s:
        return None  # daily ou padrão não suportado
    if "+" in s:
        try:
            base, inc = s.split("+", 1)
            return int(float(base) * 1000), int(float(inc) * 1000)
        except (ValueError, TypeError):
            return None
    try:
        return int(float(s) * 1000), 0
    except (ValueError, TypeError):
        return None


def is_daily(tc) -> bool:
    if tc is None:
        return False
    s = str(tc).strip()
    return bool(s) and ("/" in s)


def _clk_to_ms(h: str, m: str, s: str) -> int:
    return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)


def _strip_pgn_headers(pgn: str) -> str:
    """Remove as linhas de tags [Header "value"] e devolve só os movimentos."""
    out_lines = []
    for line in pgn.splitlines():
        if line.startswith("["):
            continue
        out_lines.append(line)
    return " ".join(out_lines).strip()


def extract_clocks(pgn: str, time_control) -> list[dict]:
    """Lê PGN e devolve lista por ply (ordem cronológica):
        [{ply, clock_ms, time_spent_ms}, ...]
    `time_spent_ms` calculado como (prev_side_clock - clock_atual + increment).
    Para o primeiro lance do lado, prev_side_clock = base do time_control.
    Retorna [] se PGN sem `%clk` ou time_control daily/inválido."""
    if not pgn:
        return []
    parsed = parse_time_control(time_control)
    if parsed is None:
        return []
    base_ms, inc_ms = parsed

    body = _strip_pgn_headers(pgn)

    # Iteração linear pelos blocos de jogada — para cada match, extrai
    # SAN + comentário ({...}) e descobre o ply (par/ímpar via "1." / "1...").
    plies: list[dict] = []
    for m in _MOVE_BLOCK_RE.finditer(body):
        move_num = int(m.group(1))
        dots = m.group(2)
        san = m.group(3)
        comment = m.group(4) or ""

        # Resultado terminal não é lance.
        if san in {"1-0", "0-1", "1/2-1/2", "*"}:
            continue

        # Lance branco = "1." (1 ponto), preto = "1..." (3 pontos).
        is_white = (len(dots) == 1)
        # Ply 1 = brancas mov 1; ply 2 = pretas mov 1; ply 3 = brancas mov 2; ...
        ply = (move_num - 1) * 2 + (1 if is_white else 2)

        clk_match = _CLK_RE.search(comment)
        if not clk_match:
            plies.append({"ply": ply, "clock_ms": None, "time_spent_ms": None})
            continue
        clk_ms = _clk_to_ms(*clk_match.groups())
        plies.append({"ply": ply, "clock_ms": clk_ms, "time_spent_ms": None})

    # Calcula time_spent caminhando por lado: prev_clock por cor.
    prev_clock = {"white": base_ms, "black": base_ms}
    for entry in plies:
        side = "white" if (entry["ply"] % 2 == 1) else "black"
        clk = entry["clock_ms"]
        if clk is None:
            continue
        spent = prev_clock[side] - clk + inc_ms
        # Saneamento: tempo negativo (relógio incoerente) vira 0; cap em 24h.
        if spent < 0:
            spent = 0
        if spent > 24 * 3600 * 1000:
            spent = 24 * 3600 * 1000
        entry["time_spent_ms"] = int(spent)
        prev_clock[side] = clk
    return plies


def initial_budget_ms(time_control) -> int | None:
    """Orçamento total inicial por lado, em ms. Daily/inválido → None."""
    parsed = parse_time_control(time_control)
    return parsed[0] if parsed else None

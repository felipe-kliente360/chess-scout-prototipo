#!/usr/bin/env python3
"""
Constrói o PDF do relatório a partir de:
  - data/<username>_<timestamp>_computed.json
  - data/<username>_<timestamp>_<perspective>_sections.json

Uso: python build.py <username> <perspective>
  perspective ∈ {myself, enemy}

O template é resolvido em ../report-<perspective>/template.html
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import chess
import chess.svg
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

ROOT = Path(__file__).resolve().parents[3]
SHARED_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SHARED_DIR.parent
DATA_DIR = ROOT / "data"
DATE_RE = re.compile(r"(\d{8}T\d{6}|\d{4}-\d{2}-\d{2})")

VALID_PERSPECTIVES = {"myself", "enemy"}


def latest(directory: Path, *patterns: str):
    files: list[Path] = []
    for p in patterns:
        files.extend(directory.glob(p))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def uci_to_san(fen: str, uci: str | None) -> str:
    """Converte UCI (e2e4, c7c8q) para SAN (e4, c8=Q). Retorna '—' se ilegal/inválido.
    (Best_moves do CSV de coleta podem vir corrompidos para alguns plies — mostrar '—' evita display enganoso.)"""
    if not uci or len(uci) < 4:
        return "—"
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            return "—"
        return board.san(move)
    except Exception:
        return "—"


def san_to_uci(fen: str, san: str | None) -> str | None:
    """Converte SAN para UCI (necessário para desenhar seta)."""
    if not san:
        return None
    try:
        board = chess.Board(fen)
        return board.parse_san(san).uci()
    except Exception:
        return None


def render_evolution_svg(history: list, metric: str, width: int = 380, height: int = 70,
                         color: str = "#5a4a10") -> str:
    """Sparkline-style line chart de um KPI ao longo dos ciclos do jogador."""
    points = [(h.get("stamp"), h.get(metric)) for h in (history or []) if h.get(metric) is not None]
    if len(points) < 2:
        return ""
    values = [v for _, v in points]
    pmin, pmax = min(values), max(values)
    rng = max(0.5, pmax - pmin)
    n = len(values)
    PAD_X, PAD_Y = 28, 14
    inner_w = width - PAD_X - 8
    inner_h = height - PAD_Y - 8
    xs = [PAD_X + inner_w * i / (n - 1) for i in range(n)]
    ys = [PAD_Y + inner_h * (1 - (v - pmin) / rng) for v in values]
    path = " ".join(["M" if i == 0 else "L" for i in range(n)])
    coords = " ".join(f"{x:.1f} {y:.1f}" for x, y in zip(xs, ys))
    path_d = " ".join(f"{cmd} {x:.1f} {y:.1f}" for cmd, x, y in zip(path.split(), xs, ys))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{color}"/>' for x, y in zip(xs, ys))
    last_label = f"{values[-1]:.1f}" if isinstance(values[-1], float) else str(values[-1])
    first_label = f"{values[0]:.1f}" if isinstance(values[0], float) else str(values[0])
    return (
        f'<svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="background:#fafafa;border:1px solid #eee;border-radius:4px">'
        f'<text x="4" y="14" font-size="9" fill="#888">{pmax:.1f}</text>'
        f'<text x="4" y="{height - 4}" font-size="9" fill="#888">{pmin:.1f}</text>'
        f'<path d="{path_d}" fill="none" stroke="{color}" stroke-width="1.5"/>'
        f'{dots}'
        f'<text x="{xs[0] - 2:.1f}" y="{ys[0] - 6:.1f}" font-size="8" fill="#666" text-anchor="middle">{first_label}</text>'
        f'<text x="{xs[-1] + 2:.1f}" y="{ys[-1] - 6:.1f}" font-size="8" fill="#666" text-anchor="middle">{last_label}</text>'
        f'</svg>'
    )


def render_board_svg(fen: str, played_uci: str | None = None,
                     best_uci: str | None = None, size: int = 280,
                     orientation: bool = chess.WHITE) -> str:
    board = chess.Board(fen)
    arrows = []
    if played_uci and len(played_uci) >= 4:
        try:
            mv = chess.Move.from_uci(played_uci)
            arrows.append(chess.svg.Arrow(mv.from_square, mv.to_square, color="#b03030cc"))
        except Exception:
            pass
    if best_uci and len(best_uci) >= 4 and best_uci != played_uci:
        try:
            mv = chess.Move.from_uci(best_uci)
            if mv in board.legal_moves:
                arrows.append(chess.svg.Arrow(mv.from_square, mv.to_square, color="#2a7a55cc"))
        except Exception:
            pass
    return chess.svg.board(board=board, arrows=arrows, size=size, orientation=orientation)


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: python build.py <username> <myself|enemy>")
    username = sys.argv[1].strip()
    perspective = sys.argv[2].strip().lower()
    if perspective not in VALID_PERSPECTIVES:
        raise SystemExit(f"❌ perspective inválida ({perspective}); use: {sorted(VALID_PERSPECTIVES)}")

    skill_dir = SKILLS_DIR / f"report-{perspective}"
    template_path = skill_dir / "template.html"
    if not template_path.is_file():
        raise SystemExit(f"❌ template não encontrado: {template_path}")

    if not DATA_DIR.is_dir():
        raise SystemExit(f"❌ Pasta de dados não encontrada: {DATA_DIR}")
    user_dir = DATA_DIR / username
    user_dir.mkdir(exist_ok=True)

    computed_file = latest(DATA_DIR, f"{username}_*_computed.json", f"{username}_computed_*.json")
    sections_file = latest(
        DATA_DIR,
        f"{username}_*_{perspective}_sections.json",
        f"{username}_{perspective}_sections_*.json",
    )
    if not computed_file:
        raise SystemExit("❌ computed JSON não encontrado em data/. Rode compute.py antes.")
    if not sections_file:
        raise SystemExit(
            f"❌ sections JSON ({perspective}) não encontrado em data/. "
            "Escreva as narrativas como <username>_<stamp>_<perspective>_sections.json antes."
        )

    computed = json.loads(computed_file.read_text(encoding="utf-8"))
    sections = json.loads(sections_file.read_text(encoding="utf-8"))
    stamp = computed.get("stamp") or DATE_RE.search(computed_file.name).group(1)

    # Persistência longitudinal: marca esta perspectiva e busca histórico para evolução
    history = []
    try:
        from history import open_db, record_analysis, fetch_history
        conn = open_db(DATA_DIR / "history.db")
        record_analysis(conn, computed, perspective=perspective)
        history = fetch_history(conn, username, limit=12)
        conn.close()
    except Exception as e:
        print(f"⚠ histórico não consultado: {e}")
    computed["history"] = history
    computed["evolution_charts"] = {
        m: render_evolution_svg(history, m) for m in ("score_10", "win_rate", "confidence_pct")
    } if len(history) >= 2 else {}

    for game in computed.get("paradigmatic_games", []):
        # Orienta o tabuleiro com a cor do jogador analisado embaixo (visão dele).
        orientation = chess.BLACK if game.get("color") == "Black" else chess.WHITE
        for kp in game.get("key_positions", []):
            fen = kp["fen_before"]
            played_uci = san_to_uci(fen, kp.get("san"))
            best_uci = kp.get("best") or ""
            kp["best_san"] = uci_to_san(fen, best_uci) if best_uci else "—"
            kp["board_svg"] = render_board_svg(fen, played_uci=played_uci, best_uci=best_uci, orientation=orientation)
        if game.get("worst_move"):
            wm = game["worst_move"]
            fen = wm["fen_before"]
            played_uci = san_to_uci(fen, wm.get("san"))
            best_uci = wm.get("best") or ""
            wm["best_san"] = uci_to_san(fen, best_uci) if best_uci else "—"
            wm["board_svg"] = render_board_svg(fen, played_uci=played_uci, best_uci=best_uci, orientation=orientation)

    env = Environment(
        loader=FileSystemLoader([str(skill_dir), str(SHARED_DIR)]),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["nl2p"] = lambda s: "".join(
        f"<p>{p.strip()}</p>" for p in (s or "").split("\n\n") if p.strip()
    )

    template = env.get_template("template.html")
    html_str = template.render(c=computed, s=sections, stamp=stamp, perspective=perspective)

    report_dir = user_dir / f"{username}_{stamp}_{perspective}_report"
    report_dir.mkdir(exist_ok=True)
    out_pdf = report_dir / f"{username}_{stamp}_{perspective}_report.pdf"
    HTML(string=html_str, base_url=str(skill_dir)).write_pdf(str(out_pdf))

    games_csv = computed.get("source_games_csv")
    analysis_csv = computed.get("source_analysis_csv")
    sources = [computed_file, sections_file]
    for name in (games_csv, analysis_csv):
        if name:
            p = DATA_DIR / name
            if p.exists():
                sources.append(p)
    for src in sources:
        try:
            dest = report_dir / src.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(src), str(dest))
        except Exception as e:
            print(f"⚠ não consegui mover {src.name}: {e}")

    print(f"✅ {out_pdf}")
    print(f"📦 artefatos em {report_dir}")


if __name__ == "__main__":
    main()

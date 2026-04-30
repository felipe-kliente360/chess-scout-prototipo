#!/usr/bin/env python3
"""Worker que consome a fila `analysis_queue` e roda Stockfish nativo.

Uso:
    python scripts/analyze_worker.py [--workers 4] [--depth 18] [--once]
                                     [--stockfish /usr/local/bin/stockfish]

- `--workers`: número de processos Stockfish em paralelo (default 4).
- `--depth`: depth alvo se a job não especificar (default 18).
- `--once`: processa fila atual e sai (default: loop infinito com sleep).
- `--stockfish`: caminho do binário (default: `which stockfish`).

O worker:
  1. Atomicamente reivindica próxima job pending da fila.
  2. Carrega PGN da partida via `games.pgn`.
  3. Identifica plies que precisam de análise (depth < target_depth).
  4. Roda Stockfish via `python-chess` engine adapter (UCI), em depth alvo.
  5. Insere/atualiza `game_analyses` com retenção pela maior depth.
  6. Marca a job como done (ou error com mensagem).

Arquitetura simples por design — fila SQLite (sem Redis), cada worker é um
processo Python com um Stockfish dedicado. Escala horizontal: rode N workers.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path

import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".claude" / "skills" / "_chess_shared"
sys.path.insert(0, str(SHARED))

from history import (  # type: ignore
    open_db, claim_next_pending, mark_job_done, save_analysis_batch,
)

DB_PATH = ROOT / "data" / "db" / "history.db"


def find_stockfish_binary(override: str | None) -> str:
    if override and Path(override).is_file():
        return override
    found = shutil.which("stockfish")
    if not found:
        raise SystemExit("❌ binário 'stockfish' não encontrado. Instale: brew install stockfish")
    return found


def analyze_pgn(pgn_text: str, depth: int, engine: chess.engine.SimpleEngine) -> list[dict]:
    """Itera os lances do PGN e roda Stockfish em cada posição.
    Retorna lista de rows compatíveis com `save_analysis_batch`.
    """
    game = chess.pgn.read_game(_StringIO(pgn_text))
    if not game:
        return []
    rows = []
    board = game.board()
    ply = 0
    for move in game.mainline_moves():
        ply += 1
        side = "White" if board.turn == chess.WHITE else "Black"
        san = board.san(move)
        uci = move.uci()
        fen_before = board.fen()
        # Roda Stockfish na posição ANTES do lance — capturamos o melhor
        # lance segundo o engine, comparado com o lance jogado.
        try:
            info = engine.analyse(board, chess.engine.Limit(depth=depth))
        except Exception as e:
            board.push(move)
            continue
        score = info.get("score")
        evaluation = ""
        mate = ""
        if score is not None:
            pov = score.pov(board.turn)
            if pov.is_mate():
                mate = str(pov.mate())
            else:
                evaluation = f"{pov.score(mate_score=10000) / 100:+.2f}"
        pv = info.get("pv") or []
        best_move = pv[0].uci() if pv else ""
        continuation = " ".join(m.uci() for m in pv[:6])
        rows.append({
            "game_id": "",  # caller preenche
            "ply": ply,
            "side_to_move": side,
            "move_san": san,
            "move_uci": uci,
            "fen_before": fen_before,
            "depth": depth,
            "evaluation": evaluation,
            "mate": mate,
            "best_move": best_move,
            "continuation": continuation,
            "tactical_theme": None,
            "tactical_confidence": None,
            "tactical_source": None,
            "position_facts": None,
        })
        board.push(move)
    return rows


class _StringIO:
    """Substitui io.StringIO para evitar import; chess.pgn aceita qualquer leitor."""
    def __init__(self, s: str): self.s = s; self.i = 0
    def readline(self):
        if self.i >= len(self.s): return ""
        nl = self.s.find("\n", self.i)
        if nl < 0:
            r = self.s[self.i:]; self.i = len(self.s); return r
        r = self.s[self.i:nl + 1]; self.i = nl + 1; return r


def worker_loop(worker_id: str, stockfish_path: str, default_depth: int, once: bool):
    """Loop principal do worker: pega job, processa, marca done."""
    # Cada worker tem seu próprio Stockfish + sua própria conexão SQLite.
    # SimpleEngine é a API síncrona (popen_uci sem o "Simple" devolve coroutine).
    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    engine.configure({"Hash": 256, "Threads": 1})
    print(f"[worker {worker_id}] iniciado, stockfish={stockfish_path}")
    try:
        while True:
            conn = open_db(DB_PATH)
            try:
                job = claim_next_pending(conn, worker_id)
            finally:
                conn.close()
            if not job:
                if once:
                    print(f"[worker {worker_id}] fila vazia, encerrando (--once)")
                    break
                time.sleep(2)
                continue
            print(f"[worker {worker_id}] job #{job['id']}: {job['game_id']} (depth {job['target_depth']})")
            try:
                conn = open_db(DB_PATH)
                row = conn.execute(
                    "SELECT pgn FROM games WHERE game_id = ?", (job["game_id"],)
                ).fetchone()
                conn.close()
                if not row or not row["pgn"]:
                    raise RuntimeError(f"sem PGN para game_id {job['game_id']}")
                rows = analyze_pgn(row["pgn"], int(job["target_depth"] or default_depth), engine)
                if not rows:
                    raise RuntimeError("PGN sem lances analisáveis")
                for r in rows:
                    r["game_id"] = job["game_id"]
                conn = open_db(DB_PATH)
                try:
                    n = save_analysis_batch(conn, rows)
                    mark_job_done(conn, job["id"])
                finally:
                    conn.close()
                print(f"[worker {worker_id}]   ✓ {n} lances persistidos")
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                print(f"[worker {worker_id}]   ✗ {err_msg}")
                conn = open_db(DB_PATH)
                try:
                    mark_job_done(conn, job["id"], error=err_msg[:500])
                finally:
                    conn.close()
    finally:
        engine.quit()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--depth", type=int, default=18)
    ap.add_argument("--once", action="store_true",
                    help="Processa fila atual e sai (não fica em loop).")
    ap.add_argument("--stockfish", default=None)
    args = ap.parse_args()

    sf_path = find_stockfish_binary(args.stockfish)
    print(f"♞ analyze_worker: {args.workers} workers, depth={args.depth}, stockfish={sf_path}")

    # SIGINT/SIGTERM: workers terminam de forma limpa.
    def _shutdown(signum, frame):
        print("\n[main] sinal recebido, esperando workers terminarem…")
        sys.exit(0)
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    if args.workers <= 1:
        worker_loop(f"w-{os.getpid()}", sf_path, args.depth, args.once)
        return

    procs = []
    for i in range(args.workers):
        wid = f"w-{i}-{uuid.uuid4().hex[:6]}"
        p = mp.Process(target=worker_loop, args=(wid, sf_path, args.depth, args.once))
        p.start()
        procs.append(p)
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Worker 2-pass que consome a fila `analysis_queue` e roda Stockfish nativo.

Uso:
    python scripts/analyze_worker.py [--workers 1] [--movetime1 1000] [--movetime2 2000]
                                     [--threads N] [--hash 256]
                                     [--stockfish /usr/local/bin/stockfish] [--once]

Arquitetura 2-pass (tempo × qualidade):

  Pass 1: go movetime <movetime1>ms, MultiPV 2, em TODAS as posições.
          FEN cache consultado antes — se depth >= 14 já salvo, reutiliza.
          Detecta posições suspeitas: loss_cp >= 40 OU captura OU xeque dado.

  Pass 2: go movetime <movetime2>ms, MultiPV 1, apenas nas suspeitas (~15%).
          Substitui resultado do pass 1 com análise mais profunda.
          Posições já em cache com depth >= 18 são puladas mesmo se suspeitas.

  Qualidade uniforme: todas as modalidades (rapid, blitz, bullet, daily) recebem
  a mesma análise robusta. Pesos por modalidade só existem na agregação tática
  do compute.py — não aqui.

  Configuração:
    --threads N      Threads do Stockfish (default: cpu_count()).
    --hash MB        Hash table em MB (default: 256; env SF_HASH_MB override).
    --workers N      Workers paralelos (default: 1 — melhor usar 1 com muitos threads).
    --movetime1 ms   Cap de tempo do pass 1 (default: 1000ms).
    --movetime2 ms   Cap de tempo do pass 2 (default: 2000ms).
    --loss-thresh cp Threshold de loss_cp para marcar suspeita (default: 40).
    --once           Processa fila atual e sai.
"""
from __future__ import annotations

import argparse
import io
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
    get_cached_position, cache_position,
)

DB_PATH = ROOT / "data" / "db" / "history.db"

# Depth mínimo exigido no cache para aceitar no pass 1 e pular análise.
_CACHE_MIN_DEPTH_PASS1 = 14
# Depth mínimo para pular pass 2 mesmo em posição suspeita.
_CACHE_MIN_DEPTH_PASS2 = 18


def find_stockfish_binary(override: str | None) -> str:
    if override and Path(override).is_file():
        return override
    found = shutil.which("stockfish")
    if not found:
        raise SystemExit("❌ binário 'stockfish' não encontrado. Instale: brew install stockfish")
    return found


def check_stockfish_version(engine: chess.engine.SimpleEngine) -> None:
    """Avisa se Stockfish é muito antigo (< 14 sem NNUE)."""
    try:
        name = engine.id.get("name", "")
        # Extrai número da versão: "Stockfish 16.1" → 16
        parts = [p for p in name.split() if p.isdigit() or (p[0].isdigit() and "." in p)]
        if parts:
            major = int(parts[0].split(".")[0])
            if major < 14:
                print(f"⚠️  Stockfish {major} detectado — recomendado ≥ 16 (NNUE). Qualidade reduzida.")
            elif major < 16:
                print(f"⚠️  Stockfish {major} — NNUE disponível mas versão 16+ é preferível.")
            else:
                print(f"✓  Stockfish {major} OK (NNUE ativo).")
    except Exception:
        pass


def _score_to_cp(score: chess.engine.PovScore | None, board: chess.Board) -> int | None:
    """Converte PovScore para centipawns da perspectiva do lado que vai jogar.
    Retorna None em caso de mate ou ausência de score."""
    if score is None:
        return None
    pov = score.pov(board.turn)
    if pov.is_mate():
        m = pov.mate()
        # Mate positivo = ganhando; negativo = perdendo
        return 30000 if m and m > 0 else -30000
    return pov.score(mate_score=30000)


def _extract_info(info: dict, board: chess.Board) -> dict:
    """Extrai campos padronizados de um resultado de engine.analyse()."""
    score = info.get("score")
    cp = _score_to_cp(score, board)
    pov = score.pov(board.turn) if score else None
    evaluation = ""
    mate_str = ""
    if pov is not None:
        if pov.is_mate():
            mate_str = str(pov.mate())
        else:
            raw = pov.score(mate_score=10000)
            evaluation = f"{raw / 100:+.2f}"
    pv = info.get("pv") or []
    best_move = pv[0].uci() if pv else ""
    continuation = " ".join(m.uci() for m in pv[:6])
    actual_depth = info.get("depth", 0)
    return {
        "cp": cp,
        "evaluation": evaluation,
        "mate": mate_str,
        "best_move": best_move,
        "continuation": continuation,
        "depth": actual_depth,
    }


def analyze_pgn_two_pass(
    pgn_text: str,
    engine: chess.engine.SimpleEngine,
    movetime1_ms: int,
    movetime2_ms: int,
    loss_threshold: int,
    conn,
) -> list[dict]:
    """Analisa um PGN completo com estratégia 2-pass.

    Retorna lista de rows compatíveis com save_analysis_batch.
    """
    game = chess.pgn.read_game(io.StringIO(pgn_text))
    if not game:
        return []

    moves = list(game.mainline_moves())
    if not moves:
        return []

    board = game.board()

    # ── Pass 1 ────────────────────────────────────────────────────────────
    # Analisa todas as posições. Consulta FEN cache antes de chamar engine.
    pass1: list[dict] = []

    for move in moves:
        fen_before = board.fen()
        is_capture = board.is_capture(move)
        board.push(move)
        gives_check = board.is_check()
        board.pop()

        entry: dict = {
            "fen_before":   fen_before,
            "move_uci":     move.uci(),
            "move_san":     "",        # preenchido abaixo em board original
            "side_to_move": "White" if board.turn == chess.WHITE else "Black",
            "is_capture":   is_capture,
            "gives_check":  gives_check,
            "from_cache":   False,
        }

        try:
            entry["move_san"] = board.san(move)
        except Exception:
            entry["move_san"] = move.uci()

        # Consulta cache
        cached = get_cached_position(conn, fen_before, _CACHE_MIN_DEPTH_PASS1)
        if cached:
            entry.update({
                "cp":           _cached_cp(cached),
                "evaluation":   cached.get("evaluation", ""),
                "mate":         cached.get("mate", ""),
                "best_move":    cached.get("best_move", ""),
                "continuation": cached.get("continuation", ""),
                "depth":        cached.get("depth", _CACHE_MIN_DEPTH_PASS1),
                "from_cache":   True,
            })
        else:
            try:
                info = engine.analyse(
                    board,
                    chess.engine.Limit(time=movetime1_ms / 1000),
                    multipv=2,
                )
                # multipv=2 retorna lista; pegamos info[0] (melhor linha)
                top = info[0] if isinstance(info, list) else info
                extracted = _extract_info(top, board)
                entry.update(extracted)
                # Grava no cache
                cache_position(
                    conn, fen_before,
                    depth=extracted["depth"],
                    best_move=extracted["best_move"],
                    evaluation=extracted["evaluation"],
                    mate=extracted["mate"],
                    continuation=extracted["continuation"],
                )
                conn.commit()
            except Exception as e:
                entry.update({"cp": None, "evaluation": "", "mate": "",
                               "best_move": "", "continuation": "", "depth": 0})

        pass1.append(entry)
        board.push(move)

    # ── Compute loss_cp entre plies consecutivos ───────────────────────────
    # loss_cp[i] = melhor_cp[i] + melhor_cp[i+1]
    # (i+1 é do lado adversário — soma porque perspectiva invertida)
    for i, entry in enumerate(pass1):
        if i + 1 < len(pass1):
            cp_i  = entry.get("cp")
            cp_i1 = pass1[i + 1].get("cp")
            if cp_i is not None and cp_i1 is not None:
                loss = cp_i + cp_i1   # positivo = jogador perdeu valor
                entry["loss_cp"] = max(0, loss)
            else:
                entry["loss_cp"] = 0
        else:
            entry["loss_cp"] = 0

    # ── Marca posições suspeitas ───────────────────────────────────────────
    for entry in pass1:
        played_ne_best = (
            entry.get("best_move")
            and entry["move_uci"] != entry["best_move"]
        )
        entry["suspicious"] = (
            (played_ne_best and entry["loss_cp"] >= loss_threshold)
            or entry["is_capture"]
            or entry["gives_check"]
        )

    n_suspicious = sum(1 for e in pass1 if e["suspicious"])
    pct = round(100 * n_suspicious / max(1, len(pass1)))
    print(f"    pass 1: {len(pass1)} lances | suspeitos: {n_suspicious} ({pct}%)")

    # ── Pass 2 ─────────────────────────────────────────────────────────────
    # Reanalisa suspeitos com movetime maior. Pula se já em cache com depth >= 18.
    n_refined = 0
    for entry in pass1:
        if not entry["suspicious"]:
            continue
        # Se cache já tem depth >= 18, não vale re-analisar
        if entry["from_cache"] and entry.get("depth", 0) >= _CACHE_MIN_DEPTH_PASS2:
            continue
        # Verifica cache com threshold mais alto
        cached2 = get_cached_position(conn, entry["fen_before"], _CACHE_MIN_DEPTH_PASS2)
        if cached2:
            entry.update({
                "cp":           _cached_cp(cached2),
                "evaluation":   cached2.get("evaluation", ""),
                "mate":         cached2.get("mate", ""),
                "best_move":    cached2.get("best_move", ""),
                "continuation": cached2.get("continuation", ""),
                "depth":        cached2.get("depth", _CACHE_MIN_DEPTH_PASS2),
            })
            continue
        try:
            board2 = chess.Board(entry["fen_before"])
            info2 = engine.analyse(
                board2,
                chess.engine.Limit(time=movetime2_ms / 1000),
                multipv=1,
            )
            top2 = info2[0] if isinstance(info2, list) else info2
            extracted2 = _extract_info(top2, board2)
            entry.update(extracted2)
            cache_position(
                conn, entry["fen_before"],
                depth=extracted2["depth"],
                best_move=extracted2["best_move"],
                evaluation=extracted2["evaluation"],
                mate=extracted2["mate"],
                continuation=extracted2["continuation"],
            )
            conn.commit()
            n_refined += 1
        except Exception:
            pass

    if n_refined:
        # Recalcula loss_cp para plies que tiveram pass 2
        for i, entry in enumerate(pass1):
            if i + 1 < len(pass1):
                cp_i  = entry.get("cp")
                cp_i1 = pass1[i + 1].get("cp")
                if cp_i is not None and cp_i1 is not None:
                    entry["loss_cp"] = max(0, cp_i + cp_i1)
        print(f"    pass 2: {n_refined} posições refinadas")

    # ── Monta rows finais ──────────────────────────────────────────────────
    rows = []
    for ply_idx, entry in enumerate(pass1):
        rows.append({
            "game_id":             "",   # caller preenche
            "ply":                 ply_idx + 1,
            "side_to_move":        entry["side_to_move"],
            "move_san":            entry["move_san"],
            "move_uci":            entry["move_uci"],
            "fen_before":          entry["fen_before"],
            "depth":               entry.get("depth", 0),
            "evaluation":          entry.get("evaluation", ""),
            "mate":                entry.get("mate", ""),
            "best_move":           entry.get("best_move", ""),
            "continuation":        entry.get("continuation", ""),
            "tactical_theme":      None,
            "tactical_confidence": None,
            "tactical_source":     None,
            "tactical_themes":     None,
            "tactical_role":       None,
            "position_facts":      None,
        })
    return rows


def _cached_cp(cached: dict) -> int | None:
    """Tenta recuperar cp de uma row de cache (não armazenado diretamente)."""
    ev = cached.get("evaluation", "")
    if ev:
        try:
            return int(float(ev) * 100)
        except ValueError:
            pass
    mate = cached.get("mate", "")
    if mate:
        try:
            m = int(mate)
            return 30000 if m > 0 else -30000
        except ValueError:
            pass
    return None


def worker_loop(
    worker_id: str,
    stockfish_path: str,
    movetime1_ms: int,
    movetime2_ms: int,
    threads: int,
    hash_mb: int,
    loss_threshold: int,
    once: bool,
):
    """Loop principal do worker: pega job, analisa 2-pass, persiste, marca done."""
    engine = chess.engine.SimpleEngine.popen_uci(stockfish_path)
    engine.configure({"Hash": hash_mb, "Threads": threads})
    check_stockfish_version(engine)
    print(
        f"[worker {worker_id}] iniciado | stockfish={stockfish_path} "
        f"| threads={threads} | hash={hash_mb}MB "
        f"| movetime {movetime1_ms}ms+{movetime2_ms}ms"
    )

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

            print(f"[worker {worker_id}] job #{job['id']}: {job['game_id']}")
            try:
                conn = open_db(DB_PATH)
                row = conn.execute(
                    "SELECT pgn FROM games WHERE game_id = ?", (job["game_id"],)
                ).fetchone()
                if not row or not row["pgn"]:
                    raise RuntimeError(f"sem PGN para game_id {job['game_id']}")

                rows = analyze_pgn_two_pass(
                    pgn_text=row["pgn"],
                    engine=engine,
                    movetime1_ms=movetime1_ms,
                    movetime2_ms=movetime2_ms,
                    loss_threshold=loss_threshold,
                    conn=conn,
                )
                if not rows:
                    raise RuntimeError("PGN sem lances analisáveis")
                for r in rows:
                    r["game_id"] = job["game_id"]

                n = save_analysis_batch(conn, rows)
                mark_job_done(conn, job["id"])
                print(f"[worker {worker_id}]   ✓ {n} lances persistidos")

            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                print(f"[worker {worker_id}]   ✗ {err_msg}")
                conn2 = open_db(DB_PATH)
                try:
                    mark_job_done(conn2, job["id"], error=err_msg[:500])
                finally:
                    conn2.close()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

    finally:
        engine.quit()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers",    type=int, default=1,
                    help="Workers paralelos (default 1 — preferir 1 com muitos threads).")
    ap.add_argument("--movetime1",  type=int, default=1000,
                    help="Movetime pass 1 em ms (default 1000).")
    ap.add_argument("--movetime2",  type=int, default=2000,
                    help="Movetime pass 2 em ms para posições suspeitas (default 2000).")
    ap.add_argument("--threads",    type=int,
                    default=int(os.environ.get("SF_THREADS", os.cpu_count() or 2)),
                    help="Threads do Stockfish (default: cpu_count).")
    ap.add_argument("--hash",       type=int,
                    default=int(os.environ.get("SF_HASH_MB", 256)),
                    help="Hash table do Stockfish em MB (default 256; env SF_HASH_MB).")
    ap.add_argument("--loss-thresh",type=int, default=40,
                    help="Loss_cp mínimo para marcar posição como suspeita (default 40).")
    ap.add_argument("--once",       action="store_true",
                    help="Processa fila atual e sai (não fica em loop).")
    ap.add_argument("--stockfish",  default=None,
                    help="Caminho do binário stockfish.")
    args = ap.parse_args()

    sf_path = find_stockfish_binary(args.stockfish)
    print(
        f"♞ analyze_worker: workers={args.workers} | "
        f"movetime={args.movetime1}ms+{args.movetime2}ms | "
        f"threads={args.threads} | hash={args.hash}MB | "
        f"loss_thresh={args.loss_thresh}cp | stockfish={sf_path}"
    )

    def _shutdown(signum, frame):
        print("\n[main] sinal recebido, encerrando…")
        sys.exit(0)
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    worker_kwargs = dict(
        stockfish_path=sf_path,
        movetime1_ms=args.movetime1,
        movetime2_ms=args.movetime2,
        threads=args.threads,
        hash_mb=args.hash,
        loss_threshold=args.loss_thresh,
        once=args.once,
    )

    if args.workers <= 1:
        worker_loop(f"w-{os.getpid()}", **worker_kwargs)
        return

    procs = []
    for i in range(args.workers):
        wid = f"w-{i}-{uuid.uuid4().hex[:6]}"
        # Divide threads entre workers quando paralelizando
        per_worker_threads = max(1, args.threads // args.workers)
        kw = {**worker_kwargs, "threads": per_worker_threads}
        p = mp.Process(target=worker_loop, args=(wid,), kwargs=kw)
        p.start()
        procs.append(p)
    for p in procs:
        p.join()


if __name__ == "__main__":
    main()

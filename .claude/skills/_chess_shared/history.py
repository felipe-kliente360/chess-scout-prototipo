"""Persistência longitudinal — SQLite com tabelas players + analyses (modelo C).

Gravado a cada execução de compute.py / build.py.
Permite renderizar evolução temporal nos relatórios e queries cross-jogador.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
  username TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  total_cycles INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,
  stamp TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  perspective TEXT,
  n_games_collected INTEGER,
  n_games_relevant INTEGER,
  win_rate REAL,
  score_10 REAL,
  acpl REAL,
  blunders INTEGER,
  mistakes INTEGER,
  inaccuracies INTEGER,
  player_rating INTEGER,
  depth INTEGER,
  confidence_pct INTEGER,
  performance_ratio REAL,
  computed_json TEXT NOT NULL,
  UNIQUE(username, stamp),
  FOREIGN KEY (username) REFERENCES players(username)
);

CREATE INDEX IF NOT EXISTS idx_analyses_username_stamp ON analyses(username, stamp);

CREATE TABLE IF NOT EXISTS position_cache (
  fen_key TEXT NOT NULL,
  depth INTEGER NOT NULL,
  best_move TEXT,
  evaluation TEXT,
  mate TEXT,
  continuation TEXT,
  analyzed_at TEXT NOT NULL,
  PRIMARY KEY (fen_key, depth)
);
CREATE INDEX IF NOT EXISTS idx_cache_fen ON position_cache(fen_key);
"""


def fen_to_key(fen: str) -> str:
    """Chave canônica do FEN: 3 primeiros campos (board + side + castling).
    Ignora ep, halfmove, fullmove para maximizar hit-rate."""
    return " ".join((fen or "").split(" ")[:3])


def get_cached_position(conn: sqlite3.Connection, fen: str, min_depth: int) -> dict | None:
    """Retorna análise cacheada se houver entry com depth >= min_depth."""
    key = fen_to_key(fen)
    cur = conn.execute("""
      SELECT depth, best_move, evaluation, mate, continuation, analyzed_at
      FROM position_cache
      WHERE fen_key = ? AND depth >= ?
      ORDER BY depth DESC
      LIMIT 1
    """, (key, min_depth))
    row = cur.fetchone()
    return dict(row) if row else None


def cache_position(conn: sqlite3.Connection, fen: str, depth: int,
                   best_move: str = "", evaluation: str = "", mate: str = "",
                   continuation: str = "") -> None:
    """Insere/atualiza entry do cache. Idempotente por (fen_key, depth)."""
    key = fen_to_key(fen)
    if not key:
        return
    conn.execute("""
      INSERT INTO position_cache (fen_key, depth, best_move, evaluation, mate, continuation, analyzed_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(fen_key, depth) DO UPDATE SET
        best_move = excluded.best_move,
        evaluation = excluded.evaluation,
        mate = excluded.mate,
        continuation = excluded.continuation,
        analyzed_at = excluded.analyzed_at
    """, (key, depth, best_move or "", evaluation or "", str(mate) if mate not in (None, "") else "",
          continuation or "", datetime.now().isoformat(timespec="seconds")))


def cache_stats(conn: sqlite3.Connection) -> dict:
    cur = conn.execute("SELECT COUNT(*) AS n, MIN(depth) AS dmin, MAX(depth) AS dmax FROM position_cache")
    row = cur.fetchone()
    return dict(row) if row else {"n": 0, "dmin": None, "dmax": None}


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Abre conexão e garante schema (idempotente)."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _safe(v):
    """SQLite não aceita NaN/inf bem."""
    if v is None:
        return None
    try:
        f = float(v)
        if f != f or f == float("inf") or f == -float("inf"):
            return None
    except (TypeError, ValueError):
        pass
    return v


def record_analysis(conn: sqlite3.Connection, computed: dict, perspective: str | None = None) -> None:
    """Upsert do jogador + insere/atualiza analysis (idempotente por (username, stamp))."""
    username = computed["username"]
    stamp = computed["stamp"]
    generated_at = computed.get("generated_at") or datetime.now().isoformat(timespec="seconds")
    sq = computed.get("sample_quality") or {}
    k = computed.get("kpis") or {}
    cal = computed.get("score_calibration") or {}

    conn.execute("""
      INSERT INTO players(username, first_seen, last_seen, total_cycles)
      VALUES (?, ?, ?, 1)
      ON CONFLICT(username) DO UPDATE SET
        last_seen = excluded.last_seen,
        total_cycles = total_cycles + 1
    """, (username, generated_at, generated_at))

    conn.execute("""
      INSERT INTO analyses (
        username, stamp, generated_at, perspective,
        n_games_collected, n_games_relevant, win_rate, score_10, acpl,
        blunders, mistakes, inaccuracies,
        player_rating, depth, confidence_pct, performance_ratio,
        computed_json
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(username, stamp) DO UPDATE SET
        generated_at = excluded.generated_at,
        perspective = COALESCE(excluded.perspective, analyses.perspective),
        n_games_collected = excluded.n_games_collected,
        n_games_relevant = excluded.n_games_relevant,
        win_rate = excluded.win_rate,
        score_10 = excluded.score_10,
        acpl = excluded.acpl,
        blunders = excluded.blunders,
        mistakes = excluded.mistakes,
        inaccuracies = excluded.inaccuracies,
        player_rating = excluded.player_rating,
        depth = excluded.depth,
        confidence_pct = excluded.confidence_pct,
        performance_ratio = excluded.performance_ratio,
        computed_json = excluded.computed_json
    """, (
        username, stamp, generated_at, perspective,
        _safe(sq.get("n_games_collected")), _safe(sq.get("n_games_relevant")),
        _safe(k.get("win_rate")), _safe(k.get("score_10")), _safe(k.get("acpl")),
        _safe(k.get("blunders")), _safe(k.get("mistakes")), _safe(k.get("inaccuracies")),
        _safe(cal.get("player_rating")), _safe(cal.get("depth")),
        _safe(sq.get("confidence_pct")), _safe(cal.get("performance_ratio")),
        json.dumps(computed, ensure_ascii=False),
    ))
    conn.commit()


def fetch_history(conn: sqlite3.Connection, username: str, limit: int = 12) -> list[dict]:
    """Últimos N ciclos do jogador, ordem cronológica (mais antigo primeiro)."""
    cur = conn.execute("""
      SELECT stamp, generated_at, perspective,
             n_games_collected, n_games_relevant, win_rate, score_10, acpl,
             blunders, mistakes, inaccuracies,
             player_rating, depth, confidence_pct, performance_ratio
      FROM (
        SELECT * FROM analyses
        WHERE username = ?
        ORDER BY stamp DESC
        LIMIT ?
      )
      ORDER BY stamp ASC
    """, (username, limit))
    return [dict(row) for row in cur.fetchall()]


def fetch_player(conn: sqlite3.Connection, username: str) -> dict | None:
    cur = conn.execute("SELECT * FROM players WHERE username = ?", (username,))
    row = cur.fetchone()
    return dict(row) if row else None


def list_players(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute("SELECT * FROM players ORDER BY last_seen DESC")
    return [dict(r) for r in cur.fetchall()]

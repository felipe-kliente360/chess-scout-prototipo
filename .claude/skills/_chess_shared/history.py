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

-- ── Persistência de partidas e análises por jogo ──────────────────────────
-- Substitui o pipeline CSV: o browser grava games após fetch do chess.com
-- e game_analyses após cada análise Stockfish. compute.py lê daqui em modo
-- --from-db (não precisa exportar/copiar CSV). Dedup automático: ao buscar
-- partidas, conferir games.game_id antes de re-fetch; ao analisar, conferir
-- game_analyses(game_id, ply, depth) e pular se depth atual ≥ requisitado.

CREATE TABLE IF NOT EXISTS games (
  game_id TEXT PRIMARY KEY,           -- chess.com URL ou hash do PGN
  username TEXT NOT NULL,
  date TEXT NOT NULL,                 -- '2026-04-15'
  color TEXT NOT NULL,                -- 'White'|'Black'
  opponent TEXT NOT NULL,
  opponent_rating INTEGER,
  my_rating INTEGER,
  result TEXT NOT NULL,               -- 'Win'|'Loss'|'Draw'
  termination TEXT,
  time_control TEXT,
  time_class TEXT,                    -- 'blitz'|'rapid'|'daily'|'bullet'
  opening TEXT,
  eco TEXT,
  eco_ply INTEGER,
  eco_family TEXT,
  url TEXT,
  pgn TEXT,
  fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_games_user ON games(username, date);
CREATE INDEX IF NOT EXISTS idx_games_user_class ON games(username, time_class);

CREATE TABLE IF NOT EXISTS game_analyses (
  game_id TEXT NOT NULL,
  ply INTEGER NOT NULL,
  side_to_move TEXT NOT NULL,
  move_san TEXT,
  move_uci TEXT,
  fen_before TEXT NOT NULL,
  depth INTEGER NOT NULL,
  evaluation TEXT,
  mate TEXT,
  best_move TEXT,
  continuation TEXT,
  tactical_theme TEXT,
  tactical_confidence REAL,
  tactical_source TEXT,
  position_facts TEXT,           -- JSON list[dict] com fatos estruturais; vazio se loss_cp < 50
  analyzed_at TEXT NOT NULL,
  PRIMARY KEY (game_id, ply)
);
CREATE INDEX IF NOT EXISTS idx_ga_game ON game_analyses(game_id);
-- Acelera games_needing_analysis e dedup-map (MIN/MAX(depth) por game_id):
CREATE INDEX IF NOT EXISTS idx_ga_game_depth ON game_analyses(game_id, depth);
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
    """Abre conexão e garante schema (idempotente). Aplica migrations leves
    (ALTER TABLE ADD COLUMN) para DBs criados antes de novas colunas existirem."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # Migrations idempotentes — ADD COLUMN só se ainda não existe.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(game_analyses)")}
    if "position_facts" not in existing_cols:
        conn.execute("ALTER TABLE game_analyses ADD COLUMN position_facts TEXT")
        conn.commit()
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


# ── Persistência de partidas + análises (substitui CSV) ──────────────────

GAME_COLUMNS = (
    "game_id", "username", "date", "color", "opponent",
    "opponent_rating", "my_rating", "result", "termination",
    "time_control", "time_class", "opening", "eco", "eco_ply",
    "eco_family", "url", "pgn", "fetched_at",
)


def upsert_game(conn: sqlite3.Connection, game: dict) -> None:
    """Insere ou atualiza uma partida. game_id deve estar presente (use url)."""
    if not game.get("game_id"):
        game = dict(game)
        game["game_id"] = game.get("url") or ""
    if not game["game_id"]:
        return
    game.setdefault("fetched_at", datetime.now().isoformat(timespec="seconds"))
    cols = ", ".join(GAME_COLUMNS)
    placeholders = ", ".join(["?"] * len(GAME_COLUMNS))
    update = ", ".join(f"{c}=excluded.{c}" for c in GAME_COLUMNS if c != "game_id")
    values = tuple(game.get(c) for c in GAME_COLUMNS)
    # Garante que username também faça upsert na tabela players (FK soft).
    if game.get("username"):
        now = game["fetched_at"]
        conn.execute("""
          INSERT INTO players(username, first_seen, last_seen, total_cycles)
          VALUES (?, ?, ?, 0)
          ON CONFLICT(username) DO UPDATE SET last_seen = excluded.last_seen
        """, (game["username"], now, now))
    conn.execute(
        f"INSERT INTO games ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(game_id) DO UPDATE SET {update}",
        values,
    )


def upsert_games_batch(conn: sqlite3.Connection, games: list[dict]) -> int:
    """Lote de upsert. Retorna número de partidas tocadas."""
    n = 0
    for g in games:
        upsert_game(conn, g)
        n += 1
    conn.commit()
    return n


def existing_game_ids(conn: sqlite3.Connection, username: str,
                      candidate_ids: list[str]) -> set[str]:
    """Quais game_ids candidatos já estão no DB pra esse user."""
    if not candidate_ids:
        return set()
    chunks = [candidate_ids[i:i+500] for i in range(0, len(candidate_ids), 500)]
    found: set[str] = set()
    for chunk in chunks:
        q = ", ".join(["?"] * len(chunk))
        cur = conn.execute(
            f"SELECT game_id FROM games WHERE username = ? AND game_id IN ({q})",
            (username, *chunk),
        )
        found |= {row["game_id"] for row in cur.fetchall()}
    return found


def fetch_games(conn: sqlite3.Connection, username: str,
                time_classes: list[str] | None = None,
                limit: int | None = None) -> list[dict]:
    """Lê partidas do DB. Se time_classes vazio/None, retorna todas."""
    sql = "SELECT * FROM games WHERE username = ?"
    args: list = [username]
    if time_classes:
        q = ", ".join(["?"] * len(time_classes))
        sql += f" AND time_class IN ({q})"
        args.extend(time_classes)
    sql += " ORDER BY date ASC, game_id ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    cur = conn.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


# ── game_analyses ─────────────────────────────────────────────────────────

ANALYSIS_COLUMNS = (
    "game_id", "ply", "side_to_move", "move_san", "move_uci",
    "fen_before", "depth", "evaluation", "mate", "best_move",
    "continuation", "tactical_theme", "tactical_confidence",
    "tactical_source", "position_facts", "analyzed_at",
)


def save_analysis_batch(conn: sqlite3.Connection, rows: list[dict]) -> int:
    """Insere/atualiza lote de lances analisados.
    Regra de retenção: PK (game_id, ply) — sobrescreve quando depth ≥ atual,
    ignora se a análise nova vem com depth menor que a já salva.
    """
    if not rows:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    placeholders = ", ".join(["?"] * len(ANALYSIS_COLUMNS))
    cols = ", ".join(ANALYSIS_COLUMNS)
    n = 0
    for r in rows:
        r = dict(r)
        r.setdefault("analyzed_at", now)
        values = tuple(r.get(c) for c in ANALYSIS_COLUMNS)
        # Só sobrescreve se a depth nova é >= depth salva. Senão keep existing.
        conn.execute(f"""
          INSERT INTO game_analyses ({cols}) VALUES ({placeholders})
          ON CONFLICT(game_id, ply) DO UPDATE SET
            side_to_move = excluded.side_to_move,
            move_san = excluded.move_san,
            move_uci = excluded.move_uci,
            fen_before = excluded.fen_before,
            depth = excluded.depth,
            evaluation = excluded.evaluation,
            mate = excluded.mate,
            best_move = excluded.best_move,
            continuation = excluded.continuation,
            tactical_theme = excluded.tactical_theme,
            tactical_confidence = excluded.tactical_confidence,
            tactical_source = excluded.tactical_source,
            position_facts = COALESCE(excluded.position_facts, game_analyses.position_facts),
            analyzed_at = excluded.analyzed_at
          WHERE excluded.depth >= game_analyses.depth
        """, values)
        n += 1
    conn.commit()
    return n


def update_position_facts_batch(conn: sqlite3.Connection,
                                items: list[tuple[str, int, str]]) -> int:
    """Atualiza só a coluna position_facts de linhas existentes.
    items = [(game_id, ply, position_facts_json), ...]. Idempotente."""
    if not items:
        return 0
    n = 0
    for game_id, ply, pf in items:
        conn.execute(
            "UPDATE game_analyses SET position_facts = ? WHERE game_id = ? AND ply = ?",
            (pf, game_id, int(ply)),
        )
        n += 1
    conn.commit()
    return n


def fetch_game_analyses(conn: sqlite3.Connection, game_id: str) -> list[dict]:
    cur = conn.execute(
        "SELECT * FROM game_analyses WHERE game_id = ? ORDER BY ply ASC",
        (game_id,),
    )
    return [dict(r) for r in cur.fetchall()]


def fetch_analyses_for_user(conn: sqlite3.Connection, username: str,
                            min_depth: int = 0,
                            game_ids: list[str] | None = None) -> list[dict]:
    """Une games + game_analyses para um user. Filtra pelo depth mínimo
    e (opcionalmente) por lista de game_ids — útil pra reduzir payload
    quando o browser só quer dedup das partidas da sessão atual."""
    sql = """
      SELECT ga.*, g.username, g.date, g.color, g.opponent, g.opponent_rating,
             g.my_rating, g.result, g.termination, g.time_class, g.url,
             g.opening, g.eco, g.eco_ply, g.eco_family, g.pgn
      FROM game_analyses ga
      JOIN games g ON g.game_id = ga.game_id
      WHERE g.username = ? AND ga.depth >= ?
    """
    args: list = [username, int(min_depth)]
    if game_ids:
        q = ", ".join(["?"] * len(game_ids))
        sql += f" AND ga.game_id IN ({q})"
        args.extend(game_ids)
    sql += " ORDER BY g.date ASC, ga.game_id ASC, ga.ply ASC"
    cur = conn.execute(sql, args)
    return [dict(r) for r in cur.fetchall()]


def games_needing_analysis(conn: sqlite3.Connection, username: str,
                           target_depth: int,
                           time_classes: list[str] | None = None) -> list[dict]:
    """Lista games do user que ainda precisam ser analisados em target_depth.
    Critério: a partida tem ZERO plies em depth >= target_depth, OU tem
    pelo menos uma com depth < target_depth (precisa reanalisar).
    """
    sql = """
      SELECT g.*,
             COUNT(ga.ply) AS plies_done,
             COALESCE(MIN(ga.depth), 0) AS min_depth_done,
             COALESCE(MAX(ga.depth), 0) AS max_depth_done
      FROM games g
      LEFT JOIN game_analyses ga ON ga.game_id = g.game_id
      WHERE g.username = ?
    """
    args: list = [username]
    if time_classes:
        q = ", ".join(["?"] * len(time_classes))
        sql += f" AND g.time_class IN ({q})"
        args.extend(time_classes)
    sql += " GROUP BY g.game_id"
    cur = conn.execute(sql, args)
    out = []
    for row in cur.fetchall():
        d = dict(row)
        # precisa analisar se nunca analisou OU se tem depth menor que o alvo
        if d["plies_done"] == 0 or d["min_depth_done"] < target_depth:
            out.append(d)
    return out


def analysis_summary(conn: sqlite3.Connection, username: str) -> dict:
    """Resumo: total de games, com análise, profundidades cobertas, posições."""
    out = {"username": username}
    out["total_games"] = conn.execute(
        "SELECT COUNT(*) AS n FROM games WHERE username = ?", (username,)
    ).fetchone()["n"]
    out["games_with_analysis"] = conn.execute("""
      SELECT COUNT(DISTINCT g.game_id) AS n FROM games g
      JOIN game_analyses ga ON ga.game_id = g.game_id
      WHERE g.username = ?
    """, (username,)).fetchone()["n"]
    out["total_positions"] = conn.execute("""
      SELECT COUNT(*) AS n FROM game_analyses ga
      JOIN games g ON g.game_id = ga.game_id
      WHERE g.username = ?
    """, (username,)).fetchone()["n"]
    cur = conn.execute("""
      SELECT depth, COUNT(*) AS n FROM game_analyses ga
      JOIN games g ON g.game_id = ga.game_id
      WHERE g.username = ?
      GROUP BY depth ORDER BY depth
    """, (username,))
    out["depth_distribution"] = {row["depth"]: row["n"] for row in cur.fetchall()}
    return out

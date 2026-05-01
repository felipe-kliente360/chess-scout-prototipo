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
-- O browser grava games após fetch do chess.com e game_analyses após cada
-- análise Stockfish. compute.py lê daqui direto. Dedup automático: ao buscar
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
  tactical_themes TEXT,          -- JSON array top-3: [{"theme":"fork","confidence":0.63}, ...]
  tactical_role TEXT,            -- 'A' oportunidade perdida | 'B' erro punido | 'C' erro não punido
  position_facts TEXT,           -- JSON list[dict] com fatos estruturais; vazio se loss_cp < 50
  clock_ms INTEGER,              -- relógio remanescente após o lance (do PGN [%clk]); NULL se sem dado
  time_spent_ms INTEGER,         -- tempo gasto naquele lance (já incluindo increment); NULL idem
  analyzed_at TEXT NOT NULL,
  PRIMARY KEY (game_id, ply)
);
CREATE INDEX IF NOT EXISTS idx_ga_game ON game_analyses(game_id);
-- Acelera games_needing_analysis e dedup-map (MIN/MAX(depth) por game_id):
CREATE INDEX IF NOT EXISTS idx_ga_game_depth ON game_analyses(game_id, depth);

-- ── Timeline tática longitudinal ──────────────────────────────────────────
-- compute.py emite ao final de cada execução. Permite comparar ciclos sem
-- reanalisar todas as partidas. period = 'YYYY-MM' da partida (não da análise).
CREATE TABLE IF NOT EXISTS tactical_timeline (
  username     TEXT NOT NULL,
  period       TEXT NOT NULL,
  time_class   TEXT NOT NULL,
  theme        TEXT NOT NULL,
  role         TEXT NOT NULL,
  weighted_sum REAL NOT NULL DEFAULT 0,
  raw_count    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (username, period, time_class, theme, role)
);

-- ── Telemetria de execução ────────────────────────────────────────────────
-- Browser registra em /api/execution-logs/start ao iniciar uma análise e
-- atualiza em /api/execution-logs/end ao concluir. Permite recalibrar
-- estimateSecondsPerPosition no index.html após acúmulo de execuções.
CREATE TABLE IF NOT EXISTS execution_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  duration_seconds REAL,
  depth INTEGER NOT NULL,
  engine TEXT NOT NULL,
  n_games INTEGER,
  n_positions_total INTEGER,
  n_positions_analyzed INTEGER,
  n_db_hits INTEGER,
  n_cache_hits INTEGER,
  n_cache_misses INTEGER,
  n_failures INTEGER,
  expected_seconds_at_start REAL,
  status TEXT
);
CREATE INDEX IF NOT EXISTS idx_exec_engine_depth ON execution_logs(engine, depth);

-- ── Fila de análise nativa (Stockfish binário) ────────────────────────────
-- Browser enfileira game_ids via /api/analyze/queue; worker(s) Python
-- consomem em paralelo, rodam Stockfish nativo e escrevem em game_analyses.
-- status: 'pending' (aguardando) | 'running' (worker pegou) | 'done' | 'error'.
CREATE TABLE IF NOT EXISTS analysis_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL,
  game_id TEXT NOT NULL,
  target_depth INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  enqueued_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  worker_id TEXT,
  error TEXT,
  UNIQUE(game_id, target_depth)
);
CREATE INDEX IF NOT EXISTS idx_aq_status ON analysis_queue(status, enqueued_at);
CREATE INDEX IF NOT EXISTS idx_aq_user ON analysis_queue(username, status);

-- ── Cache de sections (regen rápida + economia de tokens) ─────────────────
-- Salva o último sections.json + assinatura da amostra por (user, perspective).
-- Em pedidos subsequentes, skill compara a assinatura e decide reusar tudo
-- ou só os trechos que mudaram.
CREATE TABLE IF NOT EXISTS sections_cache (
  username TEXT NOT NULL,
  perspective TEXT NOT NULL,
  stamp TEXT NOT NULL,
  sections_json TEXT NOT NULL,
  signature_json TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  PRIMARY KEY (username, perspective)
);
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
    (ALTER TABLE ADD COLUMN) para DBs criados antes de novas colunas existirem.
    Modo WAL (Write-Ahead Logging): leitores e escritor coexistem sem bloquear,
    necessário quando o browser está persistindo análises e compute.py roda em
    paralelo. Cria arquivos -wal e -shm ao lado do .db."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.executescript(SCHEMA)
    # Migrations idempotentes — ADD COLUMN só se ainda não existe.
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(game_analyses)")}
    if "position_facts" not in existing_cols:
        conn.execute("ALTER TABLE game_analyses ADD COLUMN position_facts TEXT")
        conn.commit()
    if "clock_ms" not in existing_cols:
        conn.execute("ALTER TABLE game_analyses ADD COLUMN clock_ms INTEGER")
        conn.commit()
    if "time_spent_ms" not in existing_cols:
        conn.execute("ALTER TABLE game_analyses ADD COLUMN time_spent_ms INTEGER")
        conn.commit()
    if "tactical_themes" not in existing_cols:
        conn.execute("ALTER TABLE game_analyses ADD COLUMN tactical_themes TEXT")
        conn.commit()
    if "tactical_role" not in existing_cols:
        conn.execute("ALTER TABLE game_analyses ADD COLUMN tactical_role TEXT")
        conn.commit()
    # tactical_timeline pode não existir em DBs antigos — garante via CREATE IF NOT EXISTS
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS tactical_timeline (
        username     TEXT NOT NULL,
        period       TEXT NOT NULL,
        time_class   TEXT NOT NULL,
        theme        TEXT NOT NULL,
        role         TEXT NOT NULL,
        weighted_sum REAL NOT NULL DEFAULT 0,
        raw_count    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (username, period, time_class, theme, role)
      );
    """)
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


# ── Persistência de partidas + análises ──────────────────────────────────

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
    "tactical_source", "tactical_themes", "tactical_role",
    "position_facts", "analyzed_at",
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
            tactical_themes = COALESCE(excluded.tactical_themes, game_analyses.tactical_themes),
            tactical_role = COALESCE(excluded.tactical_role, game_analyses.tactical_role),
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


def backfill_clocks_for_user(conn: sqlite3.Connection, username: str) -> dict:
    """Para cada partida do user com PGN e ainda sem clock_ms preenchido,
    extrai `[%clk]` e popula clock_ms + time_spent_ms em game_analyses.
    Idempotente — só preenche linhas onde clock_ms IS NULL.

    Retorna {games_processed, plies_updated, games_skipped_no_pgn,
            games_skipped_daily, games_no_clock_data}."""
    from clock import extract_clocks  # type: ignore

    stats = {
        "games_processed": 0,
        "plies_updated": 0,
        "games_skipped_no_pgn": 0,
        "games_skipped_daily": 0,
        "games_no_clock_data": 0,
    }

    # Lista games do user que ainda têm pelo menos uma análise sem clock_ms.
    cur = conn.execute("""
      SELECT g.game_id, g.pgn, g.time_control, g.time_class
      FROM games g
      WHERE g.username = ?
        AND EXISTS (
          SELECT 1 FROM game_analyses ga
          WHERE ga.game_id = g.game_id AND ga.clock_ms IS NULL
        )
    """, (username,))
    targets = cur.fetchall()
    for row in targets:
        gid = row["game_id"]
        pgn = row["pgn"] or ""
        tc = row["time_control"]
        if not pgn:
            stats["games_skipped_no_pgn"] += 1
            continue
        # Daily / correspondência: %clk não significa pressão de tempo.
        if tc and "/" in str(tc):
            stats["games_skipped_daily"] += 1
            continue
        clocks = extract_clocks(pgn, tc)
        if not clocks:
            stats["games_no_clock_data"] += 1
            continue
        # Update por ply, só nas linhas existentes em game_analyses para esse game.
        for entry in clocks:
            if entry.get("clock_ms") is None:
                continue
            cur = conn.execute("""
              UPDATE game_analyses
              SET clock_ms = ?, time_spent_ms = ?
              WHERE game_id = ? AND ply = ? AND clock_ms IS NULL
            """, (
                entry["clock_ms"],
                entry.get("time_spent_ms"),
                gid,
                int(entry["ply"]),
            ))
            stats["plies_updated"] += cur.rowcount or 0
        stats["games_processed"] += 1
    conn.commit()
    stats["plies_with_clock_total"] = conn.execute(
        "SELECT COUNT(*) AS n FROM game_analyses ga JOIN games g ON g.game_id=ga.game_id "
        "WHERE g.username = ? AND ga.clock_ms IS NOT NULL",
        (username,),
    ).fetchone()["n"]
    return stats


def start_execution_log(conn: sqlite3.Connection, payload: dict) -> int:
    """Cria registro 'running' no início de uma análise. Retorna id."""
    started = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("""
      INSERT INTO execution_logs (
        username, started_at, depth, engine, n_games,
        n_positions_total, expected_seconds_at_start, status
      ) VALUES (?, ?, ?, ?, ?, ?, ?, 'running')
    """, (
        payload.get("username") or "",
        started,
        int(payload.get("depth") or 0),
        str(payload.get("engine") or "local"),
        _safe(payload.get("n_games")),
        _safe(payload.get("n_positions_total")),
        _safe(payload.get("expected_seconds_at_start")),
    ))
    conn.commit()
    return cur.lastrowid


def end_execution_log(conn: sqlite3.Connection, exec_id: int, payload: dict) -> bool:
    """Marca execução como completed/errored. Idempotente."""
    ended = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("""
      UPDATE execution_logs SET
        ended_at = ?,
        duration_seconds = ?,
        n_positions_analyzed = ?,
        n_db_hits = ?,
        n_cache_hits = ?,
        n_cache_misses = ?,
        n_failures = ?,
        status = ?
      WHERE id = ?
    """, (
        ended,
        _safe(payload.get("duration_seconds")),
        _safe(payload.get("n_positions_analyzed")),
        _safe(payload.get("n_db_hits")),
        _safe(payload.get("n_cache_hits")),
        _safe(payload.get("n_cache_misses")),
        _safe(payload.get("n_failures")),
        str(payload.get("status") or "completed"),
        int(exec_id),
    ))
    conn.commit()
    return (cur.rowcount or 0) > 0


def execution_calibration(conn: sqlite3.Connection, engine: str | None = None,
                          min_samples: int = 3) -> dict:
    """Retorna sec/posição observado por (engine, depth) com base em execuções
    completadas com n_positions_analyzed >= 30 (corta ruído de execuções curtas).
    Usado pelo browser para recalibrar estimateSecondsPerPosition.

    Estrutura retornada:
      {"by_engine_depth": {"local|15": {"n": 4, "sec_per_pos": 1.12, "ratio_vs_expected": 1.4}, ...},
       "n_total": int, "min_samples": int}
    """
    sql = """
      SELECT engine, depth, duration_seconds, n_positions_analyzed,
             expected_seconds_at_start, n_positions_total, n_db_hits, n_cache_hits
      FROM execution_logs
      WHERE status = 'completed'
        AND duration_seconds IS NOT NULL
        AND n_positions_analyzed IS NOT NULL
        AND n_positions_analyzed >= 30
    """
    args: list = []
    if engine:
        sql += " AND engine = ?"
        args.append(engine)
    rows = conn.execute(sql, args).fetchall()
    bucket: dict[str, list[dict]] = {}
    for r in rows:
        key = f"{r['engine']}|{int(r['depth'])}"
        bucket.setdefault(key, []).append(dict(r))
    out: dict[str, dict] = {}
    for key, items in bucket.items():
        if len(items) < min_samples:
            continue
        sec_per_pos = [it["duration_seconds"] / it["n_positions_analyzed"] for it in items]
        sec_per_pos.sort()
        median = sec_per_pos[len(sec_per_pos) // 2]
        # ratio observado vs estimado (para diagnóstico)
        ratios = []
        for it in items:
            exp = it.get("expected_seconds_at_start")
            if exp and exp > 0:
                ratios.append(it["duration_seconds"] / exp)
        ratio_median = sorted(ratios)[len(ratios) // 2] if ratios else None
        out[key] = {
            "n": len(items),
            "sec_per_pos_median": round(median, 3),
            "ratio_vs_expected_median": round(ratio_median, 3) if ratio_median else None,
        }
    return {
        "by_engine_depth": out,
        "n_total": len(rows),
        "min_samples": min_samples,
    }


# ── Sections cache (regen rápida + economia de tokens) ───────────────────

def get_cached_sections(conn: sqlite3.Connection, username: str,
                        perspective: str) -> dict | None:
    cur = conn.execute("""
      SELECT username, perspective, stamp, sections_json, signature_json, generated_at
      FROM sections_cache WHERE username = ? AND perspective = ?
    """, (username, perspective))
    row = cur.fetchone()
    return dict(row) if row else None


def save_cached_sections(conn: sqlite3.Connection, username: str, perspective: str,
                         stamp: str, sections: dict, signature: dict) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("""
      INSERT INTO sections_cache (username, perspective, stamp, sections_json, signature_json, generated_at)
      VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(username, perspective) DO UPDATE SET
        stamp = excluded.stamp,
        sections_json = excluded.sections_json,
        signature_json = excluded.signature_json,
        generated_at = excluded.generated_at
    """, (
        username, perspective, stamp,
        json.dumps(sections, ensure_ascii=False),
        json.dumps(signature, ensure_ascii=False),
        now,
    ))
    conn.commit()


def compute_sample_signature(computed: dict) -> dict:
    """Assinatura compacta da amostra usada como chave de invalidação do cache.
    Mudanças nesses campos justificam re-redação. Heurística por seção:
      - n_games / win_rate / score_10 → afeta seção 1, 2, 8, 11
      - top opening + ECO coverage → seção 5
      - tactical_themes_top top-3 → seção 4
      - paradigmatic_games (ids) → seção 7
      - score por fase → seção 2, 6
      - time_analysis median + bucket pico → seção 9
    """
    sq = computed.get("sample_quality") or {}
    k = computed.get("kpis") or {}
    bp = computed.get("by_phase") or {}
    bc = computed.get("by_color") or {}
    btc = computed.get("by_time_class") or {}
    eco = computed.get("eco_stats") or {}
    obf = computed.get("openings_by_family") or []
    tt = k.get("tactical_themes_top") or []
    pg = computed.get("paradigmatic_games") or []
    ta = computed.get("time_analysis") or {}
    return {
        "n_games": sq.get("n_games_collected"),
        "n_relevant": sq.get("n_games_relevant"),
        "confidence_pct": sq.get("confidence_pct"),
        "win_rate": k.get("win_rate"),
        "score_10": k.get("score_10"),
        "score_basis": k.get("score_10_basis"),
        "blunders": k.get("blunders"),
        "by_phase_score": {p: (bp.get(p) or {}).get("score_10") for p in ("abertura", "meio-jogo", "final")},
        "by_color_score": {c: (bc.get(c) or {}).get("score_10") for c in ("White", "Black")},
        "modalities": sorted(list(btc.keys())),
        "eco_coverage_pct": eco.get("coverage_pct"),
        "eco_avg_ply": eco.get("avg_eco_ply"),
        "top_openings": [o.get("name") for o in obf[:5]],
        "tactical_top3": [[t.get("theme"), t.get("n")] for t in tt[:3]],
        "paradigmatic_ids": [g.get("url") or g.get("game_index") for g in pg],
        "time_median_s": (ta.get("summary") or {}).get("median_time_s"),
    }


def signature_delta_flags(prev: dict, curr: dict) -> dict:
    """Compara duas assinaturas e devolve flags por seção do report.
    Cada flag ∈ {"reuse", "regenerate"}. Heurística simples:
      - n_games delta >20% → regenera tudo
      - score_10 delta >0.5 → regenera 1, 2, 6, 11
      - by_phase_score delta >0.3 numa fase → regenera 2 e 6
      - top_openings mudou → regenera 5
      - tactical_top3 mudou tema #1 → regenera 4
      - paradigmatic_ids mudou → regenera 7
      - time_median_s delta >20% → regenera 9
    """
    def fnum(x):
        try: return float(x)
        except (TypeError, ValueError): return None
    def changed(a, b, abs_tol=0.0, rel_tol=0.0):
        fa, fb = fnum(a), fnum(b)
        if fa is None and fb is None: return False
        if fa is None or fb is None: return True
        if abs_tol and abs(fa - fb) > abs_tol: return True
        if rel_tol and fa != 0 and abs(fa - fb) / max(abs(fa), 0.01) > rel_tol: return True
        return False

    out = {
        "section_1_intro": "reuse",
        "section_2_phases": "reuse",
        "section_3_colors": "reuse",
        "section_4_tactics": "reuse",
        "section_5_openings": "reuse",
        "section_6_endgames": "reuse",
        "paradigmatic_narratives": "reuse",
        "section_time_management": "reuse",
        "section_9_strengths": "reuse",
        "section_10_opponents": "reuse",
        "section_11_plan": "reuse",
        "section_puzzle_program": "reuse",
        # variantes enemy
        "section_1_profile": "reuse",
        "section_2_strengths": "reuse",
        "section_3_weaknesses": "reuse",
        "section_4_repertoire": "reuse",
        "section_5_colors": "reuse",
        "section_6_losing_patterns": "reuse",
        "section_9_battleplan": "reuse",
        "section_10_traps": "reuse",
    }

    full_regen = changed(prev.get("n_games"), curr.get("n_games"), rel_tol=0.20)
    if full_regen:
        return {k: "regenerate" for k in out}

    if changed(prev.get("score_10"), curr.get("score_10"), abs_tol=0.5):
        for k in ("section_1_intro", "section_2_phases", "section_6_endgames",
                  "section_11_plan", "section_9_strengths",
                  "section_1_profile", "section_2_strengths", "section_3_weaknesses",
                  "section_9_battleplan"):
            out[k] = "regenerate"

    prev_phase = prev.get("by_phase_score") or {}
    curr_phase = curr.get("by_phase_score") or {}
    for ph in ("abertura", "meio-jogo", "final"):
        if changed(prev_phase.get(ph), curr_phase.get(ph), abs_tol=0.3):
            out["section_2_phases"] = "regenerate"
            out["section_6_endgames"] = "regenerate"
            break

    if (prev.get("top_openings") or [])[:3] != (curr.get("top_openings") or [])[:3]:
        out["section_5_openings"] = "regenerate"
        out["section_4_repertoire"] = "regenerate"

    p_top = (prev.get("tactical_top3") or [None])[0]
    c_top = (curr.get("tactical_top3") or [None])[0]
    if p_top != c_top:
        out["section_4_tactics"] = "regenerate"

    if (prev.get("paradigmatic_ids") or []) != (curr.get("paradigmatic_ids") or []):
        out["paradigmatic_narratives"] = "regenerate"
        out["section_6_losing_patterns"] = "regenerate"

    if changed(prev.get("time_median_s"), curr.get("time_median_s"), rel_tol=0.20):
        out["section_time_management"] = "regenerate"

    return out


# ── Timeline tática longitudinal ─────────────────────────────────────────

def emit_tactical_timeline(conn: sqlite3.Connection, username: str,
                           timeline_rows: list[dict]) -> int:
    """Upsert em tactical_timeline. timeline_rows = lista de dicts com campos:
    {period, time_class, theme, role, weighted_sum, raw_count}.
    Acumula sobre execuções anteriores do mesmo mês (soma, não substitui)."""
    if not timeline_rows:
        return 0
    n = 0
    for r in timeline_rows:
        conn.execute("""
          INSERT INTO tactical_timeline
            (username, period, time_class, theme, role, weighted_sum, raw_count)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(username, period, time_class, theme, role) DO UPDATE SET
            weighted_sum = weighted_sum + excluded.weighted_sum,
            raw_count    = raw_count    + excluded.raw_count
        """, (
            username,
            str(r["period"]),
            str(r["time_class"]),
            str(r["theme"]),
            str(r["role"]),
            float(r.get("weighted_sum") or 0),
            int(r.get("raw_count") or 0),
        ))
        n += 1
    conn.commit()
    return n


def fetch_tactical_timeline(conn: sqlite3.Connection, username: str,
                             n_periods: int = 6) -> list[dict]:
    """Últimos N meses de dados táticos, ordem cronológica."""
    cur = conn.execute("""
      SELECT period, time_class, theme, role,
             SUM(weighted_sum) AS weighted_sum, SUM(raw_count) AS raw_count
      FROM tactical_timeline
      WHERE username = ?
        AND period IN (
          SELECT DISTINCT period FROM tactical_timeline
          WHERE username = ? ORDER BY period DESC LIMIT ?
        )
      GROUP BY period, time_class, theme, role
      ORDER BY period ASC, weighted_sum DESC
    """, (username, username, n_periods))
    return [dict(r) for r in cur.fetchall()]


# ── Fila de análise nativa ────────────────────────────────────────────────

def enqueue_games_for_analysis(conn: sqlite3.Connection, username: str,
                                game_ids: list[str], target_depth: int) -> dict:
    """Insere game_ids na fila. Idempotente via UNIQUE(game_id, target_depth):
    se já existe pending/running, ignora; se está 'done' ou 'error', resseta
    para pending. Retorna {enqueued, skipped_existing, reset}."""
    if not game_ids:
        return {"enqueued": 0, "skipped_existing": 0, "reset": 0}
    now = datetime.now().isoformat(timespec="seconds")
    enqueued = skipped = reset = 0
    for gid in game_ids:
        existing = conn.execute(
            "SELECT id, status FROM analysis_queue WHERE game_id = ? AND target_depth = ?",
            (gid, int(target_depth)),
        ).fetchone()
        if existing is None:
            conn.execute("""
              INSERT INTO analysis_queue (username, game_id, target_depth, status, enqueued_at)
              VALUES (?, ?, ?, 'pending', ?)
            """, (username, gid, int(target_depth), now))
            enqueued += 1
        elif existing["status"] in ("done",):
            skipped += 1
        elif existing["status"] in ("error",):
            conn.execute("""
              UPDATE analysis_queue SET status='pending', enqueued_at=?, error=NULL,
                started_at=NULL, finished_at=NULL, worker_id=NULL WHERE id=?
            """, (now, existing["id"]))
            reset += 1
        else:
            skipped += 1
    conn.commit()
    return {"enqueued": enqueued, "skipped_existing": skipped, "reset": reset}


def claim_next_pending(conn: sqlite3.Connection, worker_id: str) -> dict | None:
    """Atomicamente: pega o próximo job pending (FIFO), marca como running.
    Retorna o job ou None se fila vazia. Implementação à prova de race condition
    via UPDATE...WHERE status='pending'.
    """
    now = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("""
      UPDATE analysis_queue
      SET status='running', started_at=?, worker_id=?
      WHERE id = (
        SELECT id FROM analysis_queue WHERE status='pending'
        ORDER BY enqueued_at ASC LIMIT 1
      )
      RETURNING id, username, game_id, target_depth
    """, (now, worker_id))
    row = cur.fetchone()
    conn.commit()
    return dict(row) if row else None


def mark_job_done(conn: sqlite3.Connection, job_id: int, error: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    status = "error" if error else "done"
    conn.execute("""
      UPDATE analysis_queue SET status=?, finished_at=?, error=? WHERE id=?
    """, (status, now, error, int(job_id)))
    conn.commit()


def queue_progress(conn: sqlite3.Connection, username: str | None = None) -> dict:
    """Estatísticas da fila — útil para o browser fazer polling de progresso."""
    sql = "SELECT status, COUNT(*) AS n FROM analysis_queue"
    args: list = []
    if username:
        sql += " WHERE username = ?"
        args.append(username)
    sql += " GROUP BY status"
    rows = conn.execute(sql, args).fetchall()
    out = {"pending": 0, "running": 0, "done": 0, "error": 0}
    for r in rows:
        out[r["status"]] = r["n"]
    out["total"] = sum(out.values())
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

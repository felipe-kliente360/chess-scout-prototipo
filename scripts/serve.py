#!/usr/bin/env python3
"""Servidor local que serve index.html + endpoints REST sobre data/history.db.

Sem dependências externas — só stdlib. Substitui o pipeline CSV: o browser
posta partidas + análises pra cá; compute.py lê o mesmo .db em --from-db.

Uso:
    python scripts/serve.py [--port 8000] [--host 127.0.0.1]

Endpoints:
  GET  /api/health                                     -> {"ok": true, "db": ...}
  GET  /api/players                                    -> [{username, total_cycles, ...}]
  GET  /api/summary?username=X                         -> {total_games, depth_distribution, ...}
  GET  /api/games?username=X&time_classes=blitz,rapid  -> [game...]
  POST /api/games  body: {"games": [...]}              -> {"upserted": N}
  GET  /api/games/existing?username=X&ids=a,b,c        -> {"existing": [...]}
  GET  /api/analyses/needed?username=X&depth=15&time_classes=blitz
       -> [{game_id, plies_done, min_depth_done, ...}]  partidas que faltam analisar
  POST /api/analyses  body: {"rows": [{game_id, ply, ...}]}  -> {"saved": N}
  GET  /api/analyses?username=X&min_depth=15           -> linhas (games+analyses joined)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import urllib.parse as urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / ".claude" / "skills" / "_chess_shared"
sys.path.insert(0, str(SHARED))

from history import (  # type: ignore
    open_db, list_players, analysis_summary, fetch_games,
    upsert_games_batch, existing_game_ids, save_analysis_batch,
    fetch_analyses_for_user, games_needing_analysis, dedup_map_for_user,
)

DB_PATH = ROOT / "data" / "history.db"
WEBROOT = ROOT  # serve index.html, tactical-themes.js, data/* relativos a aqui


def _json(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.end_headers()
    handler.wfile.write(body)


def _bad(handler, msg, status=400):
    _json(handler, {"error": msg}, status=status)


def parse_csv_param(qs: dict, key: str) -> list[str]:
    raw = qs.get(key, [""])[0]
    return [x.strip() for x in raw.split(",") if x.strip()] if raw else []


class Handler(BaseHTTPRequestHandler):
    server_version = "ChessScoutLocal/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[serve] {self.address_string()} - {fmt % args}\n")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        url = urlparse.urlparse(self.path)
        qs = urlparse.parse_qs(url.query)
        path = url.path

        if path.startswith("/api/"):
            return self._handle_api_get(path, qs)

        # Serve estático: index.html, tactical-themes.js, data/*
        return self._serve_static(path)

    def do_POST(self):
        url = urlparse.urlparse(self.path)
        if not url.path.startswith("/api/"):
            return _bad(self, "POST só em /api/*", status=404)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return _bad(self, "JSON inválido")
        return self._handle_api_post(url.path, payload)

    # ── API GET ─────────────────────────────────────────────────────────
    def _handle_api_get(self, path, qs):
        conn = open_db(DB_PATH)
        try:
            if path == "/api/health":
                return _json(self, {"ok": True, "db": str(DB_PATH)})

            if path == "/api/players":
                return _json(self, list_players(conn))

            if path == "/api/summary":
                u = (qs.get("username", [""])[0] or "").strip()
                if not u: return _bad(self, "username obrigatório")
                return _json(self, analysis_summary(conn, u))

            if path == "/api/games":
                u = (qs.get("username", [""])[0] or "").strip()
                if not u: return _bad(self, "username obrigatório")
                tcs = parse_csv_param(qs, "time_classes")
                limit = qs.get("limit", [None])[0]
                limit = int(limit) if limit else None
                return _json(self, fetch_games(conn, u, tcs or None, limit))

            if path == "/api/games/existing":
                u = (qs.get("username", [""])[0] or "").strip()
                if not u: return _bad(self, "username obrigatório")
                ids = parse_csv_param(qs, "ids")
                return _json(self, {"existing": list(existing_game_ids(conn, u, ids))})

            if path == "/api/analyses/needed":
                u = (qs.get("username", [""])[0] or "").strip()
                if not u: return _bad(self, "username obrigatório")
                depth = int(qs.get("depth", ["15"])[0])
                tcs = parse_csv_param(qs, "time_classes")
                return _json(self, games_needing_analysis(conn, u, depth, tcs or None))

            if path == "/api/analyses":
                u = (qs.get("username", [""])[0] or "").strip()
                if not u: return _bad(self, "username obrigatório")
                min_depth = int(qs.get("min_depth", ["0"])[0])
                # game_ids: filtro opcional pra puxar só análises de partidas
                # específicas (reduz payload qdo browser quer só sessão atual).
                game_ids = parse_csv_param(qs, "game_ids") or None
                return _json(self, fetch_analyses_for_user(conn, u, min_depth, game_ids))

            if path == "/api/analyses/dedup-map":
                # Payload enxuto: só {game_id: {ply: depth}} pra dedup do browser.
                # ~80% menor que /api/analyses (sem evaluation/best_move/themes).
                u = (qs.get("username", [""])[0] or "").strip()
                if not u: return _bad(self, "username obrigatório")
                return _json(self, dedup_map_for_user(conn, u))

            return _bad(self, f"endpoint não encontrado: {path}", status=404)
        finally:
            conn.close()

    # ── API POST ────────────────────────────────────────────────────────
    def _handle_api_post(self, path, payload):
        conn = open_db(DB_PATH)
        try:
            if path == "/api/games":
                games = payload.get("games") or []
                if not isinstance(games, list):
                    return _bad(self, "games deve ser lista")
                n = upsert_games_batch(conn, games)
                return _json(self, {"upserted": n})

            if path == "/api/analyses":
                rows = payload.get("rows") or []
                if not isinstance(rows, list):
                    return _bad(self, "rows deve ser lista")
                n = save_analysis_batch(conn, rows)
                return _json(self, {"saved": n})

            return _bad(self, f"endpoint não encontrado: {path}", status=404)
        finally:
            conn.close()

    # ── Estático ────────────────────────────────────────────────────────
    def _serve_static(self, path):
        # Resolve "/" → /index.html
        rel = path.lstrip("/") or "index.html"
        # Bloqueio path traversal
        target = (WEBROOT / rel).resolve()
        try:
            target.relative_to(WEBROOT.resolve())
        except ValueError:
            return _bad(self, "path traversal bloqueado", status=403)
        if not target.exists() or not target.is_file():
            return _bad(self, f"arquivo não encontrado: {rel}", status=404)

        # Content-type básico por extensão
        ct = "text/plain; charset=utf-8"
        ext = target.suffix.lower()
        if ext == ".html": ct = "text/html; charset=utf-8"
        elif ext == ".js": ct = "application/javascript; charset=utf-8"
        elif ext == ".css": ct = "text/css; charset=utf-8"
        elif ext == ".json": ct = "application/json; charset=utf-8"
        elif ext == ".png": ct = "image/png"
        elif ext == ".svg": ct = "image/svg+xml"

        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Garante schema antes de aceitar conexões.
    open_db(DB_PATH).close()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"♞  chess-scout local server")
    print(f"   db    : {DB_PATH}")
    print(f"   web   : http://{args.host}:{args.port}/")
    print(f"   api   : http://{args.host}:{args.port}/api/health")
    print(f"   parar : Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nencerrando…")


if __name__ == "__main__":
    main()

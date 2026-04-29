#!/usr/bin/env python3
"""Consulta o cache de sections para (user, perspective).

Uso: python cache_lookup.py <username> <perspective>

Saída: JSON em stdout com:
  {
    "cached": bool,
    "stamp": str|null,
    "generated_at": str|null,
    "sections": {key: text} | {},
    "delta_flags": {section_key: "reuse"|"regenerate"} | {},
    "reuse_recommendation": "regenerate_all" | "partial_regen" | "full_reuse" | "no_cache"
  }

A skill (report-myself / report-enemy / report-coach) chama isto antes de
redigir. Se houver cache válido, reusa as seções marcadas "reuse" e só
re-redige as marcadas "regenerate". Economiza tokens quando o jogador
pede o mesmo relatório com poucas partidas a mais.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHARED = Path(__file__).resolve().parent
sys.path.insert(0, str(SHARED))

from history import (  # type: ignore
    open_db, get_cached_sections, compute_sample_signature, signature_delta_flags,
)

DB_PATH = ROOT / "data" / "db" / "history.db"


def latest_computed(username: str) -> dict | None:
    """Lê o computed_json mais recente do user direto da analyses table.
    Não depende do arquivo data/<user>_<stamp>_computed.json existir
    (build.py deleta após gerar PDF; só o DB é fonte canônica)."""
    conn = open_db(DB_PATH)
    try:
        cur = conn.execute("""
          SELECT computed_json FROM analyses
          WHERE username = ?
          ORDER BY stamp DESC LIMIT 1
        """, (username,))
        row = cur.fetchone()
        return json.loads(row["computed_json"]) if row else None
    finally:
        conn.close()


def main():
    if len(sys.argv) < 3:
        raise SystemExit("Uso: python cache_lookup.py <username> <perspective>")
    username = sys.argv[1].strip()
    perspective = sys.argv[2].strip().lower()
    if perspective not in {"myself", "enemy", "coach"}:
        raise SystemExit(f"perspective inválida: {perspective}")

    conn = open_db(DB_PATH)
    try:
        cached = get_cached_sections(conn, username, perspective)
    finally:
        conn.close()

    if not cached:
        print(json.dumps({
            "cached": False,
            "stamp": None,
            "generated_at": None,
            "sections": {},
            "delta_flags": {},
            "reuse_recommendation": "no_cache",
        }, ensure_ascii=False, indent=2))
        return

    # Compara assinatura cacheada vs assinatura do computed atual.
    current_computed = latest_computed(username)
    if not current_computed:
        # Cache existe mas não há computed atual — não há base de comparação.
        print(json.dumps({
            "cached": True,
            "stamp": cached.get("stamp"),
            "generated_at": cached.get("generated_at"),
            "sections": json.loads(cached.get("sections_json") or "{}"),
            "delta_flags": {},
            "reuse_recommendation": "regenerate_all",
        }, ensure_ascii=False, indent=2))
        return

    prev_sig = json.loads(cached.get("signature_json") or "{}")
    curr_sig = compute_sample_signature(current_computed)
    flags = signature_delta_flags(prev_sig, curr_sig)
    n_regen = sum(1 for v in flags.values() if v == "regenerate")
    n_reuse = sum(1 for v in flags.values() if v == "reuse")
    if n_regen == 0:
        rec = "full_reuse"
    elif n_regen >= max(1, int(0.7 * (n_regen + n_reuse))):
        rec = "regenerate_all"
    else:
        rec = "partial_regen"

    print(json.dumps({
        "cached": True,
        "stamp": cached.get("stamp"),
        "generated_at": cached.get("generated_at"),
        "sections": json.loads(cached.get("sections_json") or "{}"),
        "delta_flags": flags,
        "prev_signature": prev_sig,
        "curr_signature": curr_sig,
        "reuse_recommendation": rec,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

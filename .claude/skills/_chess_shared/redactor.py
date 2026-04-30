#!/usr/bin/env python3
"""Redator automático: chama API Anthropic com prompt caching para gerar
o sections.json a partir do computed.json.

Uso:
    python redactor.py <username> <perspective> [--model claude-opus-4-7]

Lê:
  - .claude/skills/_chess_shared/redactor_prompt.md  (instruções fixas)
  - .claude/skills/_chess_shared/theory.md           (referência conceitual)
  - .claude/skills/report-{perspective}/SKILL.md     (instruções da perspectiva)
  - data/<username>_<stamp>_computed.json            (variável)

Escreve:
  - data/<username>_<stamp>_<perspective>_sections.json

Prompt caching: as 3 partes estáticas (redactor_prompt + theory + SKILL)
ficam em `cache_control: ephemeral`. Na 2ª chamada em <5min, hit-rate
~95% — input efetivo do bilhete cai pra ~3k tokens (de ~30k).

Requer:
  - ANTHROPIC_API_KEY no env
  - pip install anthropic
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SHARED = Path(__file__).resolve().parent
SKILLS = SHARED.parent
DATA = ROOT / "data"

VALID_PERSPECTIVES = {"myself", "enemy", "coach"}
DEFAULT_MODEL = "claude-opus-4-7"


def load_static_blocks(perspective: str) -> tuple[str, str, str]:
    """Carrega os 3 blocos estáticos que entram em cache."""
    redactor_prompt = (SHARED / "redactor_prompt.md").read_text(encoding="utf-8")
    theory = (SHARED / "theory.md").read_text(encoding="utf-8")
    skill_md = (SKILLS / f"report-{perspective}" / "SKILL.md").read_text(encoding="utf-8")
    return redactor_prompt, theory, skill_md


def find_latest_computed(username: str) -> Path:
    files = sorted(DATA.glob(f"{username}_*_computed.json"))
    if not files:
        raise SystemExit(f"❌ computed.json não encontrado em {DATA}/. Rode compute.py antes.")
    return files[-1]


def call_redactor(perspective: str, computed: dict, model: str) -> dict:
    try:
        import anthropic
    except ImportError:
        raise SystemExit("❌ pip install anthropic — biblioteca não instalada.")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("❌ ANTHROPIC_API_KEY não definida no ambiente.")

    redactor_prompt, theory, skill_md = load_static_blocks(perspective)

    # System prompt com 3 blocos cacheáveis (cache_control no último de cada
    # bloco grande). Anthropic faz cache automático de blocos com >=1024 tokens.
    system_blocks = [
        {
            "type": "text",
            "text": redactor_prompt,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "## theory.md (referência conceitual canônica)\n\n" + theory,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"## SKILL.md (instruções da perspectiva {perspective})\n\n" + skill_md,
            "cache_control": {"type": "ephemeral"},
        },
    ]

    user_msg = (
        f"PERSPECTIVE: {perspective}\n\n"
        f"COMPUTED:\n{json.dumps(computed, ensure_ascii=False, indent=2)}\n\n"
        "Devolva APENAS o sections.json conforme as regras da perspectiva. JSON válido, sem markdown wrapper."
    )

    client = anthropic.Anthropic(api_key=api_key)
    print(f"♞ redactor: chamando {model} para {perspective}...")
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=system_blocks,
        messages=[{"role": "user", "content": user_msg}],
    )

    usage = resp.usage
    cache_hit = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
    print(
        f"   tokens: input={usage.input_tokens} (cache_read={cache_hit}, cache_create={cache_create}) "
        f"output={usage.output_tokens}"
    )

    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    # Remove possíveis fences de markdown.
    text = re.sub(r"^```(?:json)?\s*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"❌ resposta não é JSON válido: {e}\n\n{text[:500]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("username")
    ap.add_argument("perspective", choices=sorted(VALID_PERSPECTIVES))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args()

    computed_path = find_latest_computed(args.username)
    computed = json.loads(computed_path.read_text(encoding="utf-8"))
    stamp = computed.get("stamp")
    if not stamp:
        m = re.search(r"(\d{8}T\d{6}|\d{4}-\d{2}-\d{2})", computed_path.name)
        stamp = m.group(1) if m else "auto"

    sections = call_redactor(args.perspective, computed, args.model)

    out_path = DATA / f"{args.username}_{stamp}_{args.perspective}_sections.json"
    out_path.write_text(json.dumps(sections, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ {out_path}")


if __name__ == "__main__":
    main()

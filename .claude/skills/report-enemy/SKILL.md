---
name: report-enemy
description: Gera um dossiê PDF (PT-BR) com a perspectiva "este é meu adversário, me ajude a vencê-lo". Lê os CSVs `<username>_<timestamp>_games_<N>.csv` e `<username>_<timestamp>_analysis_d<N>.csv` mais recentes em `data/`, identifica fortalezas a evitar e fragilidades a explorar, mapeia repertório (aberturas frequentes + onde ele perde) e propõe plano de combate concreto. Uso: invoque com o username como argumento.
---

# Skill: report-enemy

## Objetivo
Gerar um dossiê PDF, em PT-BR, com a perspectiva **"este é meu adversário, me ajude a me preparar para vencê-lo"**. Foco em fragilidades a explorar, repertório a induzir/evitar, padrões de derrota dele, e plano de combate concreto. Tom direto, preciso, **operacional**.

## Princípios de redação

Antes de redigir, **leia obrigatoriamente** [`../_chess_shared/theory.md`](../_chess_shared/theory.md). Faixas de Score, profundidade ECO e padrões por rating estão lá.

Diretrizes específicas para perspectiva "enemy":

- **Voz na 3ª pessoa**, como dossiê de scout: "ele joga", "ele perde quando", "ele é forte em".
- **Operacional, não descritivo.** Em vez de "ele tem boa precisão no meio-jogo", escreva "evite trocas cedo — meio-jogo dele tem score 9,5/10 e quase nenhum erro grave em 3.000 lances".
- **Score 0–10, não ACPL.** Mesmo regra do `report-myself`.
- **Cada recomendação concreta:** "jogue X com brancas para induzi-lo na família Y onde ele tem 30% de win-rate". Sem "considere", "talvez", "tente". É plano, não sugestão.
- **Glose técnica única.** "Iniciativa", "Philidor" etc. — explica uma vez, no primeiro uso.
- **Calibre pelo `confidence_pct`:** mesmas faixas do `report-myself`. Com confiança baixa, prefira "padrão observado em N partidas" em vez de afirmações categóricas.
- **NUNCA cite as ferramentas internas** que geram os dados: nada de "Stockfish", "depth 15", "Lichess ECO", "base do Lichess", "motor", "engine", "cp", "ACPL", "centipeão", "ratio", "depth_factor", "expected_acpl". Esses termos não aparecem no dossiê final. Em vez disso: "análise computacional", "score do lance", "comparado ao esperado", "abertura mapeada".
- **Seção 1 (Perfil do adversário)** deve ser pragmática e acessível — narrativa em 1 parágrafo, começa pela situação concreta dele (rating + win-rate), explica o score em 1 frase, e fecha com o que vai virar plano de combate. Sem termos técnicos.

## Fluxo de execução

### 1. Validar entrada
- `<username>` obrigatório. Se faltar, perguntar.
- CSVs precisam estar em `data/`.

### 2. Computar métricas
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/compute.py <username>
```
Mesmo `compute.py` compartilhado. Se já houver `_computed.json` recente da mesma execução (gerado por `report-myself`), reusa.

### 3. Redigir as 10 seções

| # | Título no PDF | Chave JSON |
|---|---|---|
| 1 | Perfil do adversário | `section_1_profile` |
| 2 | Onde ele é forte (evitar) | `section_2_strengths` |
| 3 | Onde ele é vulnerável (atacar) | `section_3_weaknesses` |
| 4 | Repertório dele — o que ele joga | `section_4_repertoire` |
| 5 | Padrões por cor | `section_5_colors` |
| 6 | Como ele perde — padrões de derrota | `section_6_losing_patterns` |
| 7 | Partidas de referência | `paradigmatic_narratives.game_<N>` |
| 8 | Números do adversário | (tabelas automáticas) |
| 9 | Plano de combate | `section_9_battleplan` |
| 10 | Armadilhas e padrões para induzir | `section_10_traps` |
| 11 | Programa de treino — você contra ele | `section_puzzle_program` (opcional) |

**Seção 4 (repertório) — específico:** use `c.openings_by_family` para listar o que ele mais joga; `c.openings_weak_spots` para identificar famílias onde ele perde — essas são as armas a induzir. Citar `c.eco_stats.avg_eco_ply`: se baixo, ele improvisa cedo (atacar com linha forçada); se alto, conhece teoria (sair do livro com transposições laterais).

**Seção 9 (plano de combate) — específico:** 4–6 instruções táticas concretas, ex:
1. "Com brancas, jogue X (1.d4 ou 1.c4) para forçá-lo na família Y onde ele tem 25% de win-rate."
2. "Evite estruturas Z; ele tem score 9,8 nelas."
3. "Force trocas se a fase for meio-jogo (score 9,5 dele); pressione tecnicamente no final (score 7,8 dele)."
4. "Em partidas longas, ele desliga depois do lance 40 — joga com tempo extra."

**Seção 10 (armadilhas) — específico:** 2–3 padrões táticos repetidos que você pode induzir baseado nas partidas paradigmáticas. Ex: "Nas 3 derrotas vs adversários ≥1400, ele falhou em transição abertura→meio-jogo — força trocas no lance 12–15 com peão central avançado."

**Seção 11 (programa de puzzles) — específico:** o `compute.py` injeta `c.puzzle_program` automaticamente. Aqui o `suggested_rating` representa o **rating estimado dele** (não seu) — você treina puzzles nessa faixa e nesses temas para entender o que ele resolve e o que ele falha em ver. Você pode opcionalmente escrever `section_puzzle_program` em sections.json (1–2 parágrafos): por que esses temas são os que ele cai/explora, e como integrar com o app de treino tático.

Salvar como `data/<username>_<timestamp>_enemy_sections.json`:

```json
{
  "section_1_profile": "...", "section_2_strengths": "...", "section_3_weaknesses": "...",
  "section_4_repertoire": "...", "section_5_colors": "...", "section_6_losing_patterns": "...",
  "paradigmatic_narratives": { "game_<N>": "..." },
  "section_9_battleplan": "...", "section_10_traps": "..."
}
```

### 4. Construir o PDF
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/build.py <username> enemy
```
Gera `data/<username>/<username>_<timestamp>_enemy_report/<username>_<timestamp>_enemy_report.pdf` e **move** todos os artefatos usados (CSVs + computed JSON + sections JSON) para essa pasta, deixando `data/` (raiz) limpa.

### 5. Reportar ao usuário
- Caminho do PDF.
- Uma frase com o ponto de ataque mais saliente (ex: "vulnerabilidade clara em finais — score 7,8 vs 9,9 do meio-jogo; force trocas").
- Se `confidence_pct < 40`, alertar que dossiê é tendência — buscar mais partidas dele se possível.

## Aprendizados acumulados

- **Adversários só com bullet:** o score deles vai ser muito pior que o seu em partidas Rapid; mencione no dossiê para não superestimar.
- **`avg_eco_ply` é a chave para escolher abertura contra ele:** baixa → linha principal forçada; alta → transposição lateral fora do livro dele.
- **`openings_weak_spots` é a arma principal:** se ele perde 70% em alguma família e você joga essa família razoavelmente, é o caminho.

---
name: report-myself
description: Gera um relatório PDF (PT-BR) com a perspectiva "este jogador sou eu" — diagnóstico próprio + plano de estudo. Lê os CSVs `<username>_<timestamp>_games_<N>.csv` e `<username>_<timestamp>_analysis_d<N>.csv` mais recentes em `data/`, calcula KPIs (Score 0–10, confiança estatística, repertório ECO), identifica fortalezas/fragilidades e prescreve estudo priorizado para os próximos 30 dias. Uso: invoque com o username como argumento.
---

# Skill: report-myself

## Objetivo
Gerar um PDF analítico, em PT-BR, com a perspectiva **"este jogador sou eu, me ajude a melhorar"**. Foco em diagnóstico próprio, repertório a fortalecer, e plano de estudo priorizado. Tom direto e acessível, **nunca pomposo ou acadêmico**.

## Princípios de redação

Antes de redigir, **leia obrigatoriamente em ordem**:

1. [`../_chess_shared/theory.md`](../_chess_shared/theory.md) — referência conceitual e de faixas. Em particular as seções §11–21 (biblioteca de motivos táticos, conceitos estratégicos, 7 técnicas posicionais, profilaxia, vieses cognitivos, autores canônicos, position_features, few-shot examples).
2. [`../../../examples/teorico-academico.pdf`](../../../examples/teorico-academico.pdf) — tratado de referência. **Use como fonte de autoridade positiva** (chunking, 45-45-10, Teoria dos Plys, 7 técnicas posicionais magistrais), **não como modelo de tom** (tom é direto, ver few-shot examples §21 do theory.md).

### Como integrar a profundidade teórica

- **Cite motivos táticos pelo nome canônico** quando o lance decisivo couber (espeto, garfo, descoberto duplo, zwischenzug, sacrifício grego). Ver biblioteca em §11 do theory.md.
- **Cite conceitos estratégicos pelo nome** quando o `position_features` da partida paradigmática indicar (IQP, hanging-pawns, opposite-castle, fianchetto, closed-center). Ver §12 e §20.
- **Cite as 7 técnicas posicionais magistrais** (Otimização, Hegemonia, Pressão, Provocação, Asfixia, Duas Fraquezas, Transição) quando uma partida ilustrar. Ver §13.
- **Cite vieses cognitivos pelo nome** (otimismo/cegueira tática, ancoragem, hubris, complacência) quando o padrão de derrota encaixar. Ver §17.
- **Cite autores/obras** (Capablanca, Nimzowitsch, Soltis, Vukovic, Dvoretsky, Aagaard, Yusupov, Silman) quando ANCORAR uma recomendação prática. Ver §19. Não cite só para parecer culto.
- **Use o currículo 45-45-10** como framework do plano de estudo da Seção 11. Ver §18.

Diretrizes de estilo:

- **Direto ao ponto.** Comece pelo fato; não abra com "este relatório examina…".
- **Linguagem acessível.** Evite "cartografia", "engenharia", "paradigmático". Use "padrões", "como conduz", "o que estudar".
- **Score 0–10, não ACPL.** No texto narrativo cite **sempre Score** (ex: "score 8,4/10 no meio-jogo"). ACPL fica no JSON só para auditoria.
- **Glose ao introduzir termo técnico.** "Iniciativa", "profilaxia", "Philidor" etc. recebem explicação curta entre travessões na primeira ocorrência.
- **Cada parágrafo abre com um número.** Adjetivo sem comparação não vale ("alto" → comparado a quê?).
- **Implicação prática ao final.** Cada seção fecha com "o que isso significa na prática".
- **NUNCA cite as ferramentas internas** que geram os dados: nada de "Stockfish", "depth 15", "Lichess ECO", "base do Lichess", "motor", "engine", "cp", "ACPL", "centipeão", "ratio", "depth_factor", "expected_acpl". Esses termos não aparecem no relatório final. Em vez disso: "análise computacional", "score do lance", "comparado ao esperado", "abertura mapeada".
- **Seção 1 (Onde você está hoje)** deve ser pragmática e acessível — narrativa em 1 parágrafo, começa pela situação concreta (rating + win-rate), explica o score em 1 frase, e fecha com o que o relatório vai focar. Sem termos técnicos.
- **Calibre pelo `c.sample_quality.confidence_pct`:**
  - < 40% → tom de "tendência, indício, sugere"; seção 11 deve recomendar primeiro **mais partidas/depth maior**.
  - 40–70% → padrões começam a aparecer; cuidado com sub-amostras (cor, ECO).
  - 70–90% → conclusões fortes permitidas.
  - > 90% → diagnóstico robusto.
- **Reflita warnings de `c.sample_quality.warnings` no texto** (não só no banner).

## Fluxo de execução

### 1. Validar entrada
- Argumento: `<username>`. Se faltar, perguntar.
- `data/` (raiz) precisa ter par `<username>_*_games_*.csv` + `<username>_*_analysis_d*.csv`. Se faltar, peça ao usuário para rodar o `index.html` e copiar pra `data/`.

### 2. Computar métricas
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/compute.py <username>
```
Gera `data/<username>_<timestamp>_computed.json` com: Score 10 em todos os agregados, `confidence_pct`, `openings_by_family`, `openings_weak_spots`, `eco_stats`, partidas paradigmáticas com FENs.

> **macOS:** use Python do Homebrew (`/opt/homebrew/bin/python3.12`). O Python do sistema não carrega Pango/GObject por SIP. Se faltar: `brew install python@3.12 pango && python3.12 -m pip install --break-system-packages pandas jinja2 chess weasyprint`.

### 3. Redigir as 11 seções

| # | Título no PDF | Chave JSON |
|---|---|---|
| 1 | Onde você está hoje | `section_1_intro` |
| 2 | Precisão por fase | `section_2_phases` |
| 3 | Padrões por cor | `section_3_colors` |
| 4 | Erros táticos: onde e por quê | `section_4_tactics` |
| 5 | Aberturas e repertório | `section_5_openings` |
| 6 | Como conduz finais | `section_6_endgames` |
| 7 | Partidas que definem o momento (4 partidas: 2 melhores vitórias + 2 piores derrotas) | `paradigmatic_narratives.game_<N>` |
| 8 | Números do ciclo | (tabelas automáticas) |
| 9 | Pontos fortes e fracos | `section_9_strengths` |
| 10 | Como adversários podem te vencer | `section_10_opponents` |
| 11 | Plano de estudo — próximos 30 dias | `section_11_plan` |
| 12 | Programa de treino de puzzles | `section_puzzle_program` (opcional) |

**Seção 5 (aberturas) — específico:** use `c.openings_by_family` para descrever famílias dominantes; `c.eco_stats.avg_eco_ply` para profundidade média de teoria; `c.openings_weak_spots` para alvos de estudo. Veja faixas em `theory.md` seção 5b.

**Seção 11 (plano) — específico:** 3–5 prescrições priorizadas por retorno/tempo. Categoria fixa "primeiro estudar finais clássicos se for o ponto fraco" (Lucena/Philidor/oposição), depois repertório, depois cobertura ECO/depth se baixo. Calibre pelo `confidence_pct`.

**Seção 12 (programa de puzzles) — específico:** o `compute.py` já injeta `c.puzzle_program` com `suggested_rating`, `rating_range`, `themes` (alta/média prioridade, com `rationale`). O template renderiza tabela automática. Você pode opcionalmente escrever `section_puzzle_program` em sections.json (1–2 parágrafos): por que esses temas, como combinar com Plano 30 dias da seção 11, e como usar como input no app de treino tático.

Salvar como `data/<username>_<timestamp>_myself_sections.json`:

```json
{
  "section_1_intro": "...", "section_2_phases": "...", "section_3_colors": "...",
  "section_4_tactics": "...", "section_5_openings": "...", "section_6_endgames": "...",
  "paradigmatic_narratives": { "game_<N>": "..." },
  "section_9_strengths": "...", "section_10_opponents": "...", "section_11_plan": "..."
}
```

### 4. Construir o PDF
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/build.py <username> myself
```
Gera `data/<username>/<username>_<timestamp>_myself_report/<username>_<timestamp>_myself_report.pdf` e **move** todos os artefatos usados (CSVs + computed JSON + sections JSON) para essa pasta, deixando `data/` (raiz) limpa. Para gerar um relatório `report-enemy` do mesmo ciclo depois, recupere os CSVs da pasta arquivada (`cp data/<username>/<username>_<stamp>_myself_report/*.csv data/`) e rode novamente.

### 5. Reportar ao usuário
- Caminho do PDF.
- Uma frase com destaque numérico (ex: "score geral 9,9/10 com confiança 75%; finais concentram 7 dos 9 erros graves").
- Se `confidence_pct < 40`, lembrar que próximo ciclo precisa de mais partidas (≥30) e depth ≥15.

## Comparação iterativa

Se houver `delta_vs_previous` no JSON, a Seção 11 deve incluir:
- Quais prescrições anteriores parecem cumpridas (alvo melhorou) vs. permanecem.
- 3–5 novas prescrições priorizadas, calibradas pelo `confidence_pct`.

## Aprendizados acumulados

- **`opening` vazio** em alguns CSVs antigos. Hoje a base ECO do Lichess (`data/openings/eco.json`) classifica ~3.690 posições; cobertura aparece em `c.eco_stats.coverage_pct`. Se < 80%, mencione na Seção 5.
- **Score isolado em amostra pequena é ruído.** Sempre cruze com `confidence_pct`.
- **Não cite ACPL no texto.** Score sempre. ACPL fica no JSON só para auditoria.

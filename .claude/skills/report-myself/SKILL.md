---
name: report-myself
description: Gera um relatório PDF (PT-BR) com a perspectiva "este jogador sou eu" — diagnóstico próprio + plano de estudo. Lê dados de `data/db/history.db`. Calcula KPIs (Score 0–10, confiança estatística, repertório ECO), identifica fortalezas/fragilidades e prescreve estudo priorizado para os próximos 30 dias. Uso: invoque com o username como argumento.
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
- **Cite conceitos estratégicos pelo nome** quando o `position_facts` da partida paradigmática indicar (IQP, hanging-pawns, opposite-castle, fianchetto, closed-center). Ver §12 e §20.
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
- **Pré-requisito**: `data/db/history.db` precisa ter partidas + análises do user. Cheque rapidamente:
  ```bash
  curl -s "http://127.0.0.1:8000/api/summary?username=<username>" 2>/dev/null \
    || /opt/homebrew/bin/python3.12 -c "import sqlite3; c=sqlite3.connect('data/db/history.db'); print(c.execute('SELECT COUNT(*) FROM games WHERE username=?', ('<username>',)).fetchone()[0])"
  ```
- Se 0 partidas no DB: pedir ao usuário para iniciar o app (`/app-start` ou `bash scripts/start.sh`), abrir http://127.0.0.1:8000/ e rodar coleta + análise.

### 2. Computar métricas
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/compute.py <username>
```

Lê `data/db/history.db` (única fonte). Gera `data/<username>_<timestamp>_computed.json` com: Score 10 em todos os agregados (geral, competitivo, ponderado, média por modalidade, faixa de incerteza por depth), `confidence_pct`, `openings_by_family`, `openings_weak_spots`, `eco_stats`, `tactical_themes_top`, `tactical_themes_by_phase`, partidas paradigmáticas com FENs e temas táticos por key_position.

> **macOS:** use Python do Homebrew (`/opt/homebrew/bin/python3.12`). O Python do sistema não carrega Pango/GObject por SIP. Se faltar: `brew install python@3.12 pango && python3.12 -m pip install --break-system-packages pandas jinja2 chess weasyprint`.

### 2b. Consultar cache de sections (regen rápida + economia de tokens)

**Sempre rode antes de redigir.** O `build.py` salva o último `sections.json` por `(username, perspective)` no SQLite com assinatura da amostra. Em pedidos subsequentes, reuse o que não mudou:

```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/cache_lookup.py <username> myself
```

Saída JSON traz:
- `cached`: bool — se há cache prévio.
- `sections`: dict com seções cacheadas (`section_1_intro`, etc).
- `delta_flags`: por seção, `"reuse"` ou `"regenerate"` baseado em delta de assinatura (n_games, score_10, fases, top openings, top tactical, paradigmáticas, time_median).
- `reuse_recommendation`:
  - `"no_cache"` — cache vazio; redija tudo do zero.
  - `"full_reuse"` — nada mudou; copie literal e siga pro build.
  - `"partial_regen"` — regenere só as seções marcadas `"regenerate"`, copie as outras.
  - `"regenerate_all"` — mudança grande; redija tudo.

Em `partial_regen`, o sections.json final precisa ter **todas** as chaves (cacheadas + regeneradas). Salvar o arquivo no formato esperado por build.py: `data/<username>_<stamp>_myself_sections.json`. Economia de tokens: ~10× menos quando muda pouco.

### 3. Redigir as seções

| # | Título no PDF | Chave JSON |
|---|---|---|
| Painel | Painel do jogador | `section_panel` (opcional) |
| 1 | Situação geral | `section_1_intro` |
| 2 | Abertura e desenvolvimento | `section_opening` |
| 3 | Meio-jogo — táticas e estratégia | `section_midgame` |
| 4 | Como conduz finais | `section_endgames` |
| 5 | Padrões por cor | `section_3_colors` |
| 6 | Gestão de tempo | `section_time_management` |
| 7 | Partidas mais relevantes | `paradigmatic_narratives.game_<N>` |
| 8 | Pontos fortes e fracos | `section_9_strengths` |
| 9 | Como adversários podem te vencer | `section_10_opponents` |
| 10 | Plano de estudo — 30 dias + puzzles | `section_11_plan` + `section_puzzle_program` |

**Painel (section_panel) — opcional:** 2–3 frases que orientam o leitor antes das tabelas. Ex: "Seu score de 6,2/10 concentra a divergência no meio-jogo — é onde estão 68% dos erros graves. As seções seguintes detalham cada bloco." Se omitido, o painel abre diretamente nos KPIs.

**Seção 2 (abertura e desenvolvimento) — section_opening:** use `c.openings_by_family`, `c.eco_stats.avg_eco_ply`, `c.openings_weak_spots` e `c.by_phase` (score da fase abertura). Cubra: (a) o que você joga e com que profundidade de teoria — se `avg_eco_ply` baixo, você improvisa cedo; (b) onde você performa bem/mal na abertura (win-rate por família); (c) como a escolha de abertura afeta a transição para o meio-jogo. Veja faixas em `theory.md` seção 5b.

**Seção 3 (meio-jogo) — section_midgame:** integra táticas + padrões posicionais num único texto narrativo. Use `c.kpis.tactical_profile` e `c.position_facts_top`. Cubra: (a) temas táticos recorrentes — cite pelo nome canônico (espeto, garfo, descoberto, zwischenzug); (b) papel dominante A/B/C com implicação prática; (c) padrões posicionais que aparecem nas partidas (IQP, escudo quebrado, etc.) e como se conectam com os erros táticos; (d) score do meio-jogo vs. outras fases.

`c.kpis.tactical_profile` expõe:
- `weighted_top`: top-5 temas ponderados por papel×modalidade. Nomes seguem taxonomia Lichess exata (`fork`, `pin`, `discoveredAttack`, etc.) — use rótulos PT-BR no texto.
- `role_totals.A/B/C`: Papel A = não viu o motivo. Papel B = erro criou oportunidade que adversário aproveitou. Papel C = adversário perdoou.
- `clock_tactics.pressure_blunder_ratio`: se > 2.0, degradação severa sob pressão — mencionar em §3 e §6.
- `trend_lines`: deltas por período — use em §10 para calibrar progresso.
- `tactical_confidence.level`: se ≠ `"alta"`, adicione nota antes da narrativa. Se `"insuficiente"`, escreva só "Análise tática indisponível — amostra sem partidas rapid/blitz."

Narrativa por papel:
- A dominante: "Você não está vendo o motivo quando disponível — trabalhar recognition de padrões."
- B dominante: "Seus erros criam oportunidades que o adversário aproveita — melhorar posição antes do lance."
- C dominante: "Adversários frequentemente perdoam táticas disponíveis — nível sólido, adversário ainda erra mais."

**Seção 4 (finais) — section_endgames:** use `c.by_phase` (score e erros na fase final). Cubra: (a) score no final vs. abertura e meio-jogo — se for o ponto mais fraco, nomeie isso claramente; (b) padrões de erro característicos (prematura troca de peças, finais de torre, oposição); (c) recomendação específica (Lucena/Philidor/oposição se aplicável). Cite Capablanca ou Dvoretsky quando ancorar recomendação de finais.

**Seção 5 (por cor) — section_3_colors:** texto puro, sem tabelas (já no painel). Referencie os dados do painel. Cubra: (a) assimetria de performance brancas vs. pretas; (b) se a diferença vem de abertura ou de fase posterior; (c) implicação para escolha de repertório.

**Seção 6 (gestão de tempo) — section_time_management:** texto puro, sem blocos inline (time_analysis_block já no painel). Use `c.time_analysis` (se `available=true`). Cubra: (a) onde gasta mais tempo por fase — onde "afoga"; (b) `time_pressure.blunder_rate_ratio`: degradação real vs. neutra sob pressão; (c) "pensou e errou" (cálculo longo que falhou — viés de otimismo) vs. "errou rápido" (impulso/premove). Termine com 1 frase prática concreta. Se `available=false`, pule. Ver §22 do theory.md.

**Seção 10 (plano) — section_11_plan:** 3–5 prescrições priorizadas por retorno/tempo. Fixar "finais clássicos primeiro se for o ponto fraco" (Lucena/Philidor/oposição), depois repertório, depois cobertura ECO/depth se baixo. Use `tactical_profile.trend_lines` para indicar progresso vs. persistência. O `puzzle_program_block` é renderizado automaticamente após o texto — você pode escrever `section_puzzle_program` (1–2 parágrafos) explicando por que esses temas e como usar no Woodpecker.

Salvar como `data/<username>_<timestamp>_myself_sections.json`:

```json
{
  "section_panel": "...",
  "section_1_intro": "...",
  "section_opening": "...",
  "section_midgame": "...",
  "section_endgames": "...",
  "section_3_colors": "...",
  "section_time_management": "...",
  "paradigmatic_narratives": { "game_<N>": "..." },
  "section_9_strengths": "...",
  "section_10_opponents": "...",
  "section_11_plan": "...",
  "section_puzzle_program": "..."
}
```

### 4. Construir o PDF
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/build.py <username> myself
```

Gera `data-reports/<username>_myself_<stamp>.pdf` (pasta única, sem subpasta por user). Após o build, **deleta** os artefatos de apoio (computed.json, sections.json) — o `computed_json` fica preservado em `analyses` table no SQLite caso precise reprocessar.

Para gerar `report-enemy` do mesmo ciclo, basta rodar `compute.py <user>` de novo (o DB tem tudo).

### 5. Reportar ao usuário
- Caminho do PDF.
- Uma frase com destaque numérico (ex: "score geral 9,9/10 com confiança 75%; finais concentram 7 dos 9 erros graves").
- Se `confidence_pct < 40`, lembrar que próximo ciclo precisa de mais partidas (≥30) e depth ≥15.

## Comparação iterativa

Se houver `delta_vs_previous` no JSON, a Seção 11 deve incluir:
- Quais prescrições anteriores parecem cumpridas (alvo melhorou) vs. permanecem.
- 3–5 novas prescrições priorizadas, calibradas pelo `confidence_pct`.

## Aprendizados acumulados

- **Cobertura ECO**: a base do Lichess (`data/openings/eco.json`) classifica ~3.690 posições; cobertura aparece em `c.eco_stats.coverage_pct`. Se < 80%, mencione na Seção 5.
- **Score isolado em amostra pequena é ruído.** Sempre cruze com `confidence_pct`.
- **Não cite ACPL no texto.** Score sempre. ACPL fica no JSON só para auditoria.

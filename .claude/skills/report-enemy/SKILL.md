---
name: report-enemy
description: Gera um dossiê PDF (PT-BR) com a perspectiva "este é meu adversário, me ajude a vencê-lo". Lê dados de `data/db/history.db`. Identifica fortalezas a evitar e fragilidades a explorar, mapeia repertório (aberturas frequentes + onde ele perde) e propõe plano de combate concreto. Uso: invoque com o username como argumento.
---

# Skill: report-enemy

## Objetivo
Gerar um dossiê PDF, em PT-BR, com a perspectiva **"este é meu adversário, me ajude a me preparar para vencê-lo"**. Foco em fragilidades a explorar, repertório a induzir/evitar, padrões de derrota dele, e plano de combate concreto. Tom direto, preciso, **operacional**.

## Princípios de redação

Antes de redigir, **leia obrigatoriamente em ordem**:

1. [`../_chess_shared/theory.md`](../_chess_shared/theory.md) — referência conceitual e de faixas. Em particular as seções §11–21 (motivos táticos, conceitos estratégicos, 7 técnicas posicionais, profilaxia, vieses cognitivos, autores canônicos, position_facts, few-shot examples).
2. [`../../../examples/teorico-academico.pdf`](../../../examples/teorico-academico.pdf) — tratado de referência. **Use como fonte de autoridade positiva** (Teoria dos Plys, 7 técnicas posicionais magistrais, vieses cognitivos do oponente), **não como modelo de tom** (tom é direto e operacional).

### Como integrar a profundidade teórica no dossiê de combate

- **Seção 2 (forças):** se `position_facts` mostra que ele se sai bem em IQP/closed-center/etc., cite a estrutura pelo nome e a técnica posicional dominante. Ex: "Em estruturas IQP a favor dele, ele aplica a Hegemonia do Centro Expandido (§13.2 do tratado): controla d4/e4 e ataca a partir disso."
- **Seção 3 (vulnerabilidades):** mapeie os vieses cognitivos dele. Ex: "Padrão de derrota recorrente: viés do otimismo (§17 theory.md) — sacrifica e calcula só as variantes que funcionam, ignora refutações concretas."
- **Seção 6 (padrões de derrota):** diagnostique falhas de 2-Ply (Teoria dos Plys, §16). Quando ele perde para zwischenzug ou contra-ataque que ignorou, cite isso pelo nome.
- **Seção 9 (plano de combate):** invoque uma das 7 técnicas posicionais como instrução tática. Ex: "Aplique Restrição (técnica 5, Petrosian/Botvinnik) — neutralize o cavalo dele com h3/a3 antes de qualquer ofensiva."
- **Seção 10 (armadilhas):** cite o motivo tático canônico que você quer induzir. Ex: "Tente sacrifício grego (Bxh7+) se ele castelar curto sem estrutura defensiva — vimos que ele cai em padrões clássicos."
- **Cite obras** (Soltis para estruturas, Vukovic para ataques, Dvoretsky para finais) quando ANCORAR a recomendação tática.

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
- `data/db/history.db` precisa ter partidas + análises do user. Se vazio, pedir para o usuário rodar `/app-start` e fazer coleta + análise via UI.

### 2. Computar métricas
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/compute.py <username>
```

Lê `data/db/history.db` (única fonte). Se já houver `_computed.json` recente do mesmo ciclo (gerado por `report-myself`), reusa em vez de recomputar.

### 2b. Consultar cache de sections (regen rápida + economia de tokens)

**Sempre rode antes de redigir.** O `build.py` salva o último `sections.json` por `(username, perspective)` no SQLite com assinatura da amostra. Em pedidos subsequentes, reuse o que não mudou:

```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/cache_lookup.py <username> enemy
```

Saída JSON traz:
- `cached`: bool — se há cache prévio.
- `sections`: dict com seções cacheadas (chaves enemy: `section_1_profile`, `section_2_strengths`, etc).
- `delta_flags`: por seção, `"reuse"` ou `"regenerate"` baseado em delta de assinatura (n_games, score_10, fases, top openings, top tactical, paradigmáticas, time_median).
- `reuse_recommendation`:
  - `"no_cache"` — cache vazio; redija tudo do zero.
  - `"full_reuse"` — nada mudou; copie literal e siga pro build.
  - `"partial_regen"` — regenere só as seções marcadas `"regenerate"`, copie as outras.
  - `"regenerate_all"` — mudança grande; redija tudo.

Em `partial_regen`, o sections.json final precisa ter **todas** as chaves (cacheadas + regeneradas). Salvar como `data/<username>_<stamp>_enemy_sections.json`. Economia de tokens: ~10× menos quando muda pouco.

### 3. Redigir as seções

| # | Título no PDF | Chave JSON |
|---|---|---|
| Painel | Painel do adversário | `section_panel` (opcional) |
| 1 | Perfil do adversário | `section_1_profile` |
| 2 | Abertura e desenvolvimento | `section_opening` |
| 3 | Meio-jogo — táticas e estratégia | `section_midgame` |
| 4 | Como ele conduz finais | `section_endgames` |
| 5 | Padrões com brancas vs. pretas | `section_5_colors` |
| 6 | Gestão de tempo | `section_time_management` |
| 7 | Partidas mais relevantes | `paradigmatic_narratives.game_<N>` |
| 8 | O que evitar — onde ele é forte | `section_2_strengths` |
| 9 | Como atacar — fraquezas a explorar | `section_3_weaknesses` |
| 10 | Armadilhas e padrões a induzir | `section_10_traps` |
| 11 | Programa de treino contra ele | `section_puzzle_program` (opcional) |

**Painel (section_panel) — opcional:** 2–3 frases que orientam antes das tabelas. Ex: "Score 5,8/10 com colapso evidente no meio-jogo — a maior alavanca para te vencer. As seções seguintes detalham como explorar cada fraqueza."

**Seção 2 (abertura e desenvolvimento) — section_opening:** use `c.openings_by_family`, `c.eco_stats.avg_eco_ply`, `c.openings_weak_spots` e `c.by_phase`. Cubra: (a) o que ele joga e com que profundidade — se `avg_eco_ply` baixo, improvisa cedo (atacar com linha forçada); se alto, conhece teoria (sair do livro com transposições); (b) famílias onde ele perde mais = armas a induzir; (c) como a escolha de abertura dele configura o meio-jogo que você quer ou quer evitar.

**Seção 3 (meio-jogo) — section_midgame:** integra táticas + padrões posicionais em texto único com foco operacional. Use `c.kpis.tactical_profile` e `c.position_facts_top`. Cubra: (a) temas táticos onde ele erra mais — **Papel B** (erros que criam oportunidades imediatas) são prioridade; (b) padrões posicionais fracos (win_rate baixo quando presente) = estruturas a forçar; (c) como os dois se conectam num plano concreto de como pressionar. Score do meio-jogo vs. outras fases.

`c.kpis.tactical_profile` expõe os padrões táticos dele:
- `weighted_top`: top-5 temas ponderados. Papel B = fragilidades reais a induzir. Papel C = situações em que ele perdoa — você vai aproveitar.
- `role_totals.B` alto: erros criam oportunidades imediatas — jogue posições táticas abertas.
- `clock_tactics.pressure_blunder_ratio` > 2.0: ele colapsa sob pressão — force complicações no terço final.
- `clock_tactics.under_pressure.themes_top3`: erros a provocar quando o relógio dele está baixo.
- `trend_lines`: temas com `delta > 0` piorando — prioridade. `delta < 0` melhorando — não contar com eles.
- `tactical_confidence.level`: se ≠ `"alta"`, adicione nota antes da narrativa. Se `"insuficiente"`, não cite temas específicos.

**Seção 4 (finais) — section_endgames:** use `c.by_phase` (score da fase final dele). Cubra: (a) score no final vs. outras fases — se for pior, é onde você quer chegar; (b) tipos de final onde ele mais erra; (c) instrução concreta (ex: "force troca de damas no lance 20–25 para chegarm num final de torres onde ele tem score 6,8").

**Seção 5 (por cor) — section_5_colors:** texto puro, sem tabelas (já no painel). Cubra: (a) assimetria dele — ele joga melhor com uma cor? (b) implicação para você: se ele é fraco com pretas numa família, jogar 1.e4/1.d4 para forçar essa situação.

**Seção 6 (gestão de tempo) — section_time_management:** texto puro. Use `c.time_analysis`. Foco na exploração tática: (a) onde ele afoga ou desliga no relógio; (b) `time_pressure.blunder_rate_ratio` > 1.5 = ele desmonta sob pressão — acelere e force complicações no terço final; (c) "pensou e errou" = viés do otimismo dele, atacar com refutações concretas; (d) "errou rápido" = premove, induzir sequências forçadas. Encerre com 1 instrução tática concreta. Se `available=false`, pule.

**Seção 9 (como atacar) — section_3_weaknesses:** 4–6 instruções táticas operacionais. Ex: "Com brancas, jogue 1.d4 para forçá-lo na família Y onde tem 25% de win-rate." "Force trocas no meio-jogo (score 9,5 dele); pressione no final (score 7,2)." Sem "considere" ou "talvez" — é plano, não sugestão.

**Seção 10 (armadilhas) — section_10_traps:** 2–3 padrões táticos repetidos que você pode induzir com base nas paradigmáticas. Cite o motivo tático canônico a induzir (sacrifício grego, zwischenzug, espeto na coluna aberta).

**Seção 11 (programa de puzzles) — section_puzzle_program:** `suggested_rating` = rating estimado dele — você treina nessa faixa para entender o que ele falha em ver. Temas `source="detected"` = fraquezas concretas das partidas reais dele. Opcional: 1–2 parágrafos explicando como usar no Woodpecker.

Salvar como `data/<username>_<timestamp>_enemy_sections.json`:

```json
{
  "section_panel": "...",
  "section_1_profile": "...",
  "section_opening": "...",
  "section_midgame": "...",
  "section_endgames": "...",
  "section_5_colors": "...",
  "section_time_management": "...",
  "paradigmatic_narratives": { "game_<N>": "..." },
  "section_2_strengths": "...",
  "section_3_weaknesses": "...",
  "section_10_traps": "...",
  "section_puzzle_program": "..."
}
```

### 4. Construir o PDF
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/build.py <username> enemy
```

Gera `data-reports/<username>_enemy_<stamp>.pdf` (pasta única). Após o build, **deleta** computed.json e sections.json — `computed_json` fica preservado em `analyses` table no SQLite.

### 5. Reportar ao usuário
- Caminho do PDF.
- Uma frase com o ponto de ataque mais saliente (ex: "vulnerabilidade clara em finais — score 7,8 vs 9,9 do meio-jogo; force trocas").
- Se `confidence_pct < 40`, alertar que dossiê é tendência — buscar mais partidas dele se possível.

## Aprendizados acumulados

- **Adversários só com bullet:** o score deles vai ser muito pior que o seu em partidas Rapid; mencione no dossiê para não superestimar.
- **`avg_eco_ply` é a chave para escolher abertura contra ele:** baixa → linha principal forçada; alta → transposição lateral fora do livro dele.
- **`openings_weak_spots` é a arma principal:** se ele perde 70% em alguma família e você joga essa família razoavelmente, é o caminho.

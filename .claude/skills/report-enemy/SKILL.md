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
| 9 | Gestão de tempo dele | `section_time_management` |
| 10 | Plano de combate | `section_9_battleplan` |
| 11 | Armadilhas e padrões para induzir | `section_10_traps` |
| 12 | Programa de treino — você contra ele | `section_puzzle_program` (opcional) |

**Seção 3 (vulnerabilidades táticas) — use `tactical_profile` do adversário:**

`c.kpis.tactical_profile` expõe os padrões táticos dele:
- `weighted_top`: top-5 temas ponderados por papel×modalidade. **Papel B** (adversário aproveitou erro dele) = fragilidades reais — são os temas a induzir. **Papel C** (adversário não aproveitou) = situações em que ele perdoa oponentes — indique que você vai aproveitar quando aparecer.
- `role_totals.B` alto: os erros dele frequentemente criam oportunidades imediatas — ataque com posições táticas abertas.
- `clock_tactics.pressure_blunder_ratio` > 2.0: sob pressão de relógio ele colapsa taticamente — jogue partidas longas com reserva de tempo no final; force complicações no terço final.
- `clock_tactics.under_pressure.themes_top3`: quais temas aparecem quando o relógio está baixo — esses são os erros a provocar no final da partida.
- `trend_lines`: temas com `delta > 0` estão piorando (ele está errando mais neles). Themes com `delta < 0` estão melhorando (evitar contar com eles se estiver em queda recente).

Nomes de tema seguem taxonomia Lichess (`fork`, `pin`, `discoveredAttack`, `backRankMate`, `capturingDefender`, `intermezzo`, `kingsideAttack`, etc.) — use rótulos PT-BR no texto.

**Seção 4 (repertório) — específico:** use `c.openings_by_family` para listar o que ele mais joga; `c.openings_weak_spots` para identificar famílias onde ele perde — essas são as armas a induzir. Citar `c.eco_stats.avg_eco_ply`: se baixo, ele improvisa cedo (atacar com linha forçada); se alto, conhece teoria (sair do livro com transposições laterais).

**Seção 9 (gestão de tempo dele) — específico:** use `c.time_analysis`. Foque na exploração tática: (a) como ele administra o relógio (mediana por fase) — onde ele "afoga" ou "desliga"; (b) leitura de `time_pressure.blunder_rate_ratio`: razão >1.5 indica que ele desmonta sob pressão (acelere; force trocas/complicações no terço final); (c) padrão de "pensou e errou" (top `long_think_blunders`) — viés do otimismo dele em cálculo longo, atacar com posições onde refutação é concreta; (d) "errou rápido" (top `fast_blunders`) — premove ou reflexo, induzir lances forçados em sequência. Encerre com 1 instrução tática (ex: "complique no lance 25–35 — é onde a curva de erro dele dispara em pressão"). Se `available=false`, pule.

**Seção 10 (plano de combate) — específico:** 4–6 instruções táticas concretas, ex:
1. "Com brancas, jogue X (1.d4 ou 1.c4) para forçá-lo na família Y onde ele tem 25% de win-rate."
2. "Evite estruturas Z; ele tem score 9,8 nelas."
3. "Force trocas se a fase for meio-jogo (score 9,5 dele); pressione tecnicamente no final (score 7,8 dele)."
4. "Em partidas longas, ele desliga depois do lance 40 — joga com tempo extra."

**Seção 10 (armadilhas) — específico:** 2–3 padrões táticos repetidos que você pode induzir baseado nas partidas paradigmáticas. Ex: "Nas 3 derrotas vs adversários ≥1400, ele falhou em transição abertura→meio-jogo — força trocas no lance 12–15 com peão central avançado."

**Seção 11 (programa de puzzles) — específico:** o `compute.py` injeta `c.puzzle_program` automaticamente. Aqui o `suggested_rating` representa o **rating estimado dele** (não seu) — você treina puzzles nessa faixa e nesses temas para entender o que ele resolve e o que ele falha em ver. Temas com `source="detected"` vêm das partidas reais dele — são as fraquezas concretas a explorar. **Os nomes em `puzzle_program.themes[].theme` são camelCase Lichess exato** — compatíveis com o Woodpecker para montar sessões de treino. Você pode opcionalmente escrever `section_puzzle_program` em sections.json (1–2 parágrafos): por que esses temas são os que ele cai/explora, e como integrar com o app de treino tático.

Salvar como `data/<username>_<timestamp>_enemy_sections.json`:

```json
{
  "section_1_profile": "...", "section_2_strengths": "...", "section_3_weaknesses": "...",
  "section_4_repertoire": "...", "section_5_colors": "...", "section_6_losing_patterns": "...",
  "paradigmatic_narratives": { "game_<N>": "..." },
  "section_time_management": "...",
  "section_9_battleplan": "...", "section_10_traps": "..."
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

---
name: report-coach
description: Gera um relatório PDF (PT-BR) na perspectiva "este aluno é meu — me ajude a treiná-lo". Lê `data/db/history.db`. Foco em delta vs ciclo anterior + comparativo com outros alunos da base + plano didático com exercícios e livros. Uso B2B (treinador/escola). Invoque com o username do aluno.
---

# Skill: report-coach

## Objetivo

Gerar PDF analítico, em PT-BR, voz **treinador → aluno**: diagnóstico + delta vs ciclo anterior + comparativo cross-aluno + plano didático prescritivo com exercícios concretos. Tom direto, autoritativo mas acolhedor — não acadêmico, não pomposo.

Diferença operacional vs `/report-myself`:
- **Foco no delta**, não no estado absoluto. Se é o primeiro ciclo do aluno, plano didático tem mais peso.
- **Comparativo cross-aluno** explícito (percentil entre os players da base do treinador).
- **Plano de estudo** descritivo: livros + exercícios + cronograma + métrica de sucesso para próxima aula.

## Princípios de redação

Antes de redigir, **leia obrigatoriamente em ordem**:

1. [`../_chess_shared/theory.md`](../_chess_shared/theory.md) — referência conceitual e biblioteca de motivos. Em particular §11–21.
2. [`../../../examples/teorico-academico.pdf`](../../../examples/teorico-academico.pdf) — autoridade positiva (Teoria dos Plys, 7 técnicas posicionais).

Diretrizes específicas:

- **Voz "treinador → aluno".** "O aluno...", "Para a próxima aula prescreva...", "Recomendo trabalhar...". Implica que o leitor é o treinador, mas o tom é o que o treinador diria ao aluno na sessão.
- **Delta primeiro, estado depois.** Cada seção começa pelo que mudou ("Score subiu de 4,8 → 5,5 desde o ciclo anterior — meio-jogo concentra o ganho").
- **Sempre prescreva exercício concreto** ao final de cada seção: "30 minutos de puzzles tema X", "estude o capítulo Y do livro Z", "joga 10 partidas brancas em Sistema W".
- **Cite obras canônicas** (Silman Reassess Your Chess, Dvoretsky Endgame Manual, Vukovic Art of Attack, Yusupov 9 volumes, Aagaard) com edição/capítulo quando ANCORA prescrição. Ver §19 theory.md.
- **NUNCA cite ferramentas internas** (Stockfish, depth, ECO, motor, ACPL, cp). Use "análise computacional", "score do lance", "abertura mapeada".
- **Score 0–10, não ACPL.**
- **Comparativo cross-aluno** (Seção 4) — descreva onde o aluno está em relação aos outros da base SEM nomear ninguém ("entre os 6 alunos analisados, este está no 3º lugar em Score; abaixo da média em profundidade de teoria").
- **Calibre pelo `confidence_pct`:** mesmas faixas de myself.
- **Plano didático** (Seção 9) deve ter cronograma semanal explícito + métrica de validação para próxima aula ("se na próxima aula o blunder rate em meio-jogo cair de 22 para <15, exercício funcionou").

## Fluxo de execução

### 1. Validar entrada
- Argumento: `<username>` do aluno. Se faltar, perguntar.
- DB precisa ter partidas + análises do user.

### 2. Computar métricas
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/compute.py <username>
```

### 2b. Cache de sections
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/cache_lookup.py <username> coach
```

Mesmas regras de myself/enemy: `full_reuse` → copia, `partial_regen` → regenera só seções com flag, `regenerate_all` → tudo do zero.

### 3. Redigir as 10 seções

| # | Título no PDF | Chave JSON |
|---|---|---|
| 1 | Aluno e ciclo | `section_1_student` |
| 2 | Delta vs ciclo anterior — onde acelerou | `section_2_progress` |
| 3 | Onde regrediu ou estagnou | `section_3_regression` |
| 4 | Comparativo com outros alunos | `section_4_benchmark` |
| 5 | Padrão dominante atual (fase + tema + estrutura) | `section_5_dominant_pattern` |
| 6 | Partidas mais educativas do ciclo | `paradigmatic_narratives.game_<N>` |
| 7 | Números do ciclo | (tabelas automáticas) |
| 8 | Diagnóstico de tempo | `section_time_management` |
| 9 | Plano didático — próximas 4 semanas | `section_9_lesson_plan` |
| 10 | Sinais para próxima aula | `section_10_next_session` |
| 11 | Programa de puzzles atribuído | `section_puzzle_program` (opcional) |

**Seção 5 (padrão dominante) — use `tactical_profile` para diagnóstico tático do aluno:**

`c.kpis.tactical_profile` disponibiliza:
- `weighted_top`: top-5 temas ponderados por papel×modalidade. Use para nomear o **padrão dominante atual** — o 1º tema é o foco de prescrição da Seção 9. **Nomes seguem taxonomia Lichess** (`fork`, `pin`, `discoveredAttack`, `capturingDefender`, `backRankMate`, etc.).
- `role_totals`:
  - `A` alto → aluno não vê motivos quando estão disponíveis: prescrever **puzzle training de recognition**, não cálculo.
  - `B` alto → erros do aluno são explorados: foco em **posições antes do lance errado** (prevenção, profilaxia).
  - `C` alto → adversários são fracos e perdoam: aluno está evoluindo bem, elevar o nível dos oponentes.
- `clock_tactics.pressure_blunder_ratio`: se > 2.0 → gestão de tempo é urgente; incluir exercícios com relógio (jogo rápido com limite restrito).
- `clock_tactics.under_pressure.themes_top3`: os padrões que colapsa sob pressão — prescrever puzzles desses temas especificamente em modo blitz.
- `trend_lines`: temas com `delta > 0` estão piorando — são os targets da próxima semana. Temas com `delta < 0` estão melhorando — mencionar como progresso observado.

Woodpecker: temas de `puzzle_program.themes[].theme` são camelCase Lichess exato — passam direto para o Woodpecker montar o conjunto de treino do aluno.

**Seção 4 (benchmark) — específico:** use `c.coach_benchmarks` (injetado pelo build.py em perspective=coach). Estrutura:
```
{
  "available": true,
  "n_students": int,
  "aluno": {score_10, win_rate, confidence_pct, eco_avg_ply, ...},
  "percentile": {score_10: 60.0, win_rate: 80.0, ...},  // em [0,100]
  "all": [{username: "você"|"aluno_N", is_you: bool, ...}, ...]
}
```
Descreva onde o aluno está sem nomear os outros. Ex: "Score do aluno (5,5) está no percentil 60 entre os 6 alunos da base — acima da mediana mas abaixo do top-2. Win-rate 93% é alto mas vem de adversários fracos." Se `available=false` (n_students<2), pule explicando que ainda não há base de comparação suficiente.

**Seção 9 (plano didático) — específico:** cronograma de 4 semanas em forma de tabela mental. Cada semana tem: foco temático, exercício concreto (livro/capítulo + 30min puzzle tema X), métrica para próxima aula. Exemplo:
- Semana 1: meio-jogo combinatório — Yusupov vol.1 cap.5 + 30min/dia puzzles (tema top-1 de `tactical_profile.weighted_top`, ex: `pin` ou `fork`) em rating sugerido pelo `puzzle_program`. Métrica: blunder rate cai de 22 para <15.
- Semana 2: técnica de finais — Dvoretsky Endgame Manual cap.4 (Lucena) + cap.5 (Philidor). Métrica: na próxima sessão, demonstrar Lucena no quadro.
- Semana 3: aprofundar repertório principal (Caro-Kann ou Sistema Londres) até 8 lances de teoria. Livro: Soltis Pawn Structure Chess para entender plano.
- Semana 4: revisar 5 partidas paradigmáticas com o treinador, cada uma com foco em 1 técnica posicional (Silman Reassess Your Chess).

**Seção 10 (sinais próxima aula) — específico:** 3–5 indicadores objetivos que o treinador deve checar na próxima sessão para validar se o plano funcionou. Ex: "(1) blunder rate meio-jogo: medir nas próximas 30 partidas; (2) profundidade ECO: avg_ply deve subir de 3,8 para ≥6; (3) demonstrar Lucena oralmente no quadro; (4) Score competitivo (n≥15) — pedir ao aluno enfrentar adversários ±100 Elo do rating."

Salvar como `data/<username>_<timestamp>_coach_sections.json`:

```json
{
  "section_1_student": "...", "section_2_progress": "...", "section_3_regression": "...",
  "section_4_benchmark": "...", "section_5_dominant_pattern": "...",
  "paradigmatic_narratives": { "game_<N>": "..." },
  "section_time_management": "...",
  "section_9_lesson_plan": "...", "section_10_next_session": "..."
}
```

### 4. Construir o PDF
```bash
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/build.py <username> coach
```

Gera `data-reports/<username>_coach_<stamp>.pdf`. Após build, deleta computed.json + sections.json (preservados em `analyses` table + `sections_cache`).

### 5. Reportar ao usuário
- Caminho do PDF.
- Uma frase com delta principal (ex: "Score subiu de 4,8 → 5,5 desde o ciclo anterior; finais técnicos continuam sendo o gargalo — 4 semanas de Dvoretsky priorizadas").
- Se primeiro ciclo do aluno, mencionar que próximos relatórios terão delta + comparativo com a evolução individual.

## Aprendizados acumulados

- **Comparativo cross-aluno só vale com ≥3 players.** Em base pequena, vira só "este aluno tem Score X". Use `coach_benchmarks.n_students` para decidir tom.
- **Sem ciclo anterior, Seção 2 (progresso) vira "linha de base".** Não force narrativa de evolução se é o primeiro relatório do aluno.
- **Plano didático precisa de obra + capítulo + métrica.** "Estudar finais" sem livro nem prazo não vale; o aluno não age.

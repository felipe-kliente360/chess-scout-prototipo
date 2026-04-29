# chess-scout-prototipo

Gerador de relatórios analíticos de xadrez (PDF, PT-BR) para jogadores de Chess.com. Coleta partidas, analisa cada lance com **Stockfish + tema tático + fatos estruturais** (3 camadas determinísticas e complementares), persiste tudo em SQLite local e produz dois tipos de dossiê:

- **`/report-myself <user>`** — perspectiva "este jogador sou eu". Diagnóstico próprio + plano de estudo de 30 dias.
- **`/report-enemy <user>`** — perspectiva "este é meu adversário". Plano de combate concreto.

---

## Por que existe

Análises padrão do Chess.com e Lichess respondem **"o que aconteceu nesta partida?"**. Este projeto responde:

- **"O que precisa estudar nos próximos 30 dias?"**
- **"Como me preparar para enfrentar este adversário específico?"**
- **"Em que padrões estruturais o jogador vence — e em quais ele cai?"**

Três perguntas que ferramentas comerciais não atendem com profundidade.

## Diferenciais

| Item | Chess.com / Lichess | Este projeto |
|---|---|---|
| **Score** | Accuracy 0–100% absoluta | **Score 0–10 canônico** (subset competitivo, ±10% Elo) com blend de 50% ACPL + 30% win-rate + 20% redução de blunders, calibrado por curva chess.com empírica e penalizado quando ACPL é implausível para o rating (sinal de motor). Faixa de incerteza ±0.2 a ±1.5 dependendo do depth. |
| **Análise por posição** | Só Stockfish | **3 camadas independentes**: Stockfish + tema tático (308k puzzles do woodpecker) + 24 fatos estruturais determinísticos |
| **Filtragem** | Inclui tudo | Filtro de relevância (descarta curtas, abandonos, early timeout/resign) — universo analítico vs. histórico real separados |
| **Aberturas** | Identifica ECO | Mapeia repertório completo + identifica weak spots + recomenda trocas concretas |
| **Lances paradigmáticos** | Mostra blunders | **Vitória**: 2 melhores + 1 pior do jogador. **Derrota**: 2 piores do jogador + 1 melhor do adversário. Spread temporal mínimo (8 plies), ordem cronológica. |
| **Plano de ação** | Genérico | Prescrições priorizadas por retorno/esforço + programa de puzzles |
| **Persistência** | Histórico no site | **SQLite local** com `players` + `analyses` + `games` + `game_analyses` + `position_cache` + `position_facts` cacheados |
| **Pipeline** | Web only | **Servidor Python local** (stdlib) elimina CSV manual; dedup automático por `(game_id, ply, depth)` — re-análises instantâneas |
| **Lifecycle** | Browser sempre aberto | Slash commands `/app-start` e `/app-stop` orquestram processos em background |
| **Output** | PDF baixado | **`data-reports/<user>_<perspective>_<stamp>.pdf`**, sem JSON de apoio (preservado em `analyses` table) |
| **Linguagem** | Inglês técnico | **PT-BR direto** (proibidas referências a "Stockfish", "ACPL", "centipeão" no texto final) |

---

## Como tudo funciona — visão de alto nível

### 1. Liga o app

```bash
bash scripts/start.sh         # ou via Claude Code: /app-start
```

Sobe servidor stdlib (`scripts/serve.py`) em `http://127.0.0.1:8000/` em background, valida `/api/health`, registra PID em `.app-state.json` e tenta abrir o navegador. Sem dependências além do Python (Flask **não** é necessário). Idempotente — chamar de novo é no-op.

### 2. Configura na UI

Abrir **http://127.0.0.1:8000/** (badge verde fixo `SERVER MODE · history.db` confirma o modo). Define:

- **Username** chess.com
- **Quantidade** partidas/formato — cap automático: `qtd × n_formatos ≤ 400`
- **Depth Stockfish** — default **15** (recomendado); hint dinâmico exibe ±incerteza por depth (±1.5 em d10, ±0.5 em d15, ±0.2 em d18+)
- **Engine** — Stockfish local WASM (Hash 256MB) ou API remota stockfish.online
- **Formatos** — bullet/blitz/rapid/daily

### 3. Coleta — botão "Buscar Partidas"

```
Browser → api.chess.com → ECO classifier → POST /api/games → SQLite
```

- Lista archives chess.com do user
- Itera meses do mais recente ao antigo, filtra por formato + n_plies ≥ 15
- Quotas independentes por formato (50 blitz **+** 50 rapid, não misturado)
- Classifica abertura via base ECO Lichess (3.690 posições, varredura até 25 plies)
- **Persiste** cada partida em `games` (UPSERT idempotente por URL chess.com — re-coletar nunca duplica)

### 4. Análise — botão "⚙ Analisar Stockfish"

**Pré-flight**:
- Estima tempo total; se >30 min pede confirmação modal
- Carrega `eco.json`, `position_cache.json`, `themes_index.json` (todos lazy)
- `GET /api/analyses?username=X&game_ids=...` traz só análises das partidas da sessão (payload proporcional)
- Inicializa engine WASM com `setoption name Hash value 256` (tabela de transposição expandida)

**Loop por lance** — duas camadas em paralelo no browser:

1. **Stockfish** — `evaluation`, `mate`, `best_move`, `continuation`. Dedup hierárquico: se já tem em `game_analyses` com depth ≥ alvo, **reusa direto**; senão consulta `position_cache.json`; senão chama o engine.
2. **Tema tático** — `TacticalThemes.classifyPosition(fen, best, played)` consulta `themes_index.json` (4 MB, 32k fingerprints B + 2.5k C, do release [woodpecker-puzzles](https://github.com/felipe-kliente360/woodpecker-puzzles)). Retorna `{theme, confidence, source}`.

**Persistência ao terminar cada partida** (não a cada N lances): `POST /api/analyses` em batch. UPSERT segue regra "maior depth vence" — d15 sobrescreve d10, d8 não sobrescreve d15.

### 5. Compute do relatório

```bash
python3.12 .claude/skills/_chess_shared/compute.py <username>
```

Lê `games + game_analyses` direto do SQLite. **Terceira camada (fatos estruturais)** roda aqui em todo lance com `loss_cp ≥ 50` via `position_facts.py` (24 detectores determinísticos), com cache delta no DB pra próximas execuções. Produz `data/<user>_<stamp>_computed.json` com:

- **Score canônico (`kpis.score_10`)** + variantes auxiliares + `score_10_basis` indicando a base
- **Banda de incerteza** por depth — relator deve usar como faixa, não ponto
- **Por fase / cor / time_class / família ECO**
- **Aberturas weak spots** (n≥5 e win-rate <40%)
- **Tactical themes top** + correlação por resultado
- **Position facts top** + correlação
- **4 partidas paradigmáticas** (2 melhores vitórias + 2 piores derrotas) com 3 `key_positions` cada — cada uma carregando as 3 camadas juntas

### 6. Skill — PDF

```
/report-myself <user>     # ou /report-enemy <user>
```

A skill lê o computed JSON + `theory.md` (referência teórica), redige seções em PT-BR direto citando motivos pelo nome canônico (garfo, IQP, escudo quebrado) ancorados em autores (Capablanca, Nimzowitsch, Soltis, Vukovic, Dvoretsky). `build.py` renderiza HTML + WeasyPrint → PDF em **`data-reports/<user>_<perspective>_<stamp>.pdf`**, e **deleta** computed.json + sections.json (preservados no SQLite via `analyses.computed_json`).

### 7. Desliga o app

```bash
bash scripts/stop.sh          # ou /app-stop
```

Lê `.app-state.json`, SIGTERM gracioso (1s), SIGKILL nos sobreviventes, limpa estado. Idempotente.

### 8. Re-análises são instantâneas

- Coletar partidas: `games` faz UPSERT idempotente — re-coletar não duplica.
- Re-analisar com mesma depth: dedup pula 100% do Stockfish.
- Subir depth (15 → 18): só re-roda nas plies onde a depth nova > existente.
- Position facts: cacheados no DB após primeira execução de `compute.py`.
- Tactical themes: classificação pura no browser, instantânea.
- Re-gerar relatório: `compute.py + build.py` em ~5s pra um usuário com cache completo.

---

## Arquitetura

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (http://127.0.0.1:8000/)                            │
│  • chess.js + stockfish.js (WASM Hash 256MB)                 │
│  • tactical-themes.js (consulta themes_index.json)           │
│  • Carrega ECO + position_cache lazy                         │
└────────────────┬─────────────────────────────────────────────┘
                 │  REST API (/api/games, /api/analyses, ...)
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  scripts/serve.py (stdlib http.server)                       │
│  • UPSERT idempotente em games + game_analyses               │
│  • Filtra por game_ids para payload enxuto                   │
│  • Endpoints: health, players, summary, games(/existing),    │
│    analyses(/needed)                                         │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  data/history.db (SQLite, fonte única)                       │
│  ├── players (usuários conhecidos)                           │
│  ├── games (UPSERT por URL chess.com)                        │
│  ├── game_analyses (PK game_id+ply, +position_facts cache)   │
│  ├── analyses (snapshot do compute por (user, stamp))        │
│  └── position_cache (cache compartilhado por FEN)            │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  compute.py <user>                                           │
│  • Score blend canônico (50% ACPL + 30% wr + 20% blunder)    │
│    × engine_factor (penalidade motor) × variante eleita      │
│    por hierarquia (competitive ≥15 → modality_avg → overall) │
│  • Position_facts in-flight com cache delta no DB            │
│  • Aggregados táticos + estruturais com win-rate             │
│  • Paradigmáticas: 2 melhores + 1 pior (vitória),            │
│                    2 piores + 1 advers. (derrota)            │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────────────────────────┐
│  Skill (Claude Code)                                         │
│  • Redige sections.json em PT-BR (theory.md guia tom)        │
│  • build.py: Jinja2 + python-chess SVG + WeasyPrint          │
└────────────────┬─────────────────────────────────────────────┘
                 │
                 ▼
       data-reports/<user>_<perspective>_<stamp>.pdf
       (computed.json + sections.json deletados após render)
```

---

## Estrutura do projeto

```
chess-scout-prototipo/
├── index.html                            # UI: coletor + analisador (browser)
├── tactical-themes.js                    # Classificador tático (browser)
├── README.md
├── ROADMAP.md
│
├── data/                                 # Bases canônicas + DB local
│   ├── history.db                        # SQLite — fonte única (PII, gitignored)
│   ├── openings/
│   │   ├── eco.json                      # Base ECO Lichess (3.690 posições, versionado)
│   │   ├── *.tsv                         # TSVs raw Lichess (versionado)
│   │   └── position_cache.json           # Cache do browser (gitignored)
│   └── tactical/
│       └── themes_index.json             # Índice tático 4 MB (versionado)
│
├── data-reports/                         # PDFs finais (gitignored, PII)
│   └── <user>_<perspective>_<stamp>.pdf
│
├── scripts/
│   ├── start.sh                          # /app-start (idempotente, registra PIDs)
│   ├── stop.sh                           # /app-stop (SIGTERM → SIGKILL → limpa estado)
│   ├── serve.py                          # Servidor local (stdlib)
│   ├── build_eco_index.py                # Constrói eco.json (rebuild raro)
│   └── build_tactical_index.py           # Constrói themes_index.json
│
├── tests/
│   ├── conftest.py
│   ├── test_helpers.py                   # Score, depth_factor, classify_loss…
│   └── test_history.py                   # SQLite + cache de posições
│
└── .claude/
    ├── settings.json
    ├── commands/                         # Slash commands
    │   ├── app-start.md
    │   ├── app-stop.md
    │   ├── report-myself.md
    │   └── report-enemy.md
    └── skills/
        ├── _chess_shared/
        │   ├── compute.py                # Pipeline analítico
        │   ├── build.py                  # Renderização PDF
        │   ├── history.py                # SQLite schema + helpers
        │   ├── position_facts.py         # 24 detectores estruturais
        │   ├── theory.md                 # Referência conceitual + tom
        │   ├── base.css
        │   └── macros.html
        ├── report-myself/
        │   ├── SKILL.md
        │   └── template.html
        └── report-enemy/
            ├── SKILL.md
            └── template.html
```

---

## Conceitos centrais

### Score 0–10 — modelo final

```
score_10 = 10 × engine_factor × (
  0.5 × ACPL_score      # exp(-(acpl_d20_eq / expected_acpl(rating)) / 2)
+ 0.3 × win_score       # win_rate / 100
+ 0.2 × blunder_score   # 1 / (1 + bpm/5), bpm = blunders por 100 lances
)
```

- **`expected_acpl(rating)`**: curva chess.com empírica (não a teórica antiga). Âncoras: 1000:120, 1400:80, 1800:50, 2200:30, 2500:20.
- **`engine_factor`**: penalidade quando `ACPL_d20 / expected < 0.5` (sinal de motor). Linear de 1.0 (ratio ≥0.5) até piso 0.5 (ratio = 0). Só aplica em amostra ≥100 lances.

**Variantes calculadas** (todas com mesmo blend, em subsets diferentes):
- `score_10_overall` — todas as partidas relevantes
- `score_10_competitive` — só adversários em `±max(150, 10% rating)` Elo
- `score_10_weighted` — peso `exp(-(gap/300)²)` por gap
- `score_10_by_modality_avg` — média aritmética dos competitivos por time_class

**`kpis.score_10` canônico (Opção B)** — hierarquia:
1. `competitive` se `n_competitive_games ≥ 15` ← preferido
2. `modality_avg` se ≥2 modalidades com ≥10 partidas
3. `overall` como fallback

`kpis.score_10_basis` documenta a base eleita.

### Faixa de incerteza por depth

| Depth | Banda | Leitura |
|---|---|---|
| ≤10 | ±1.5 | Preview — só erros grosseiros |
| 12 | ±1.0 | Rápido, magnitude duvidosa |
| **15** | **±0.5** | **Padrão recomendado** |
| 18+ | ±0.2 | Análise séria |

### As 3 camadas de análise por posição

1. **Stockfish**: avaliação numérica, melhor lance, mate.
2. **Tactical theme** (`tactical_theme`, `tactical_confidence`, `tactical_source`): classificação automática via fingerprint de delta best-vs-played (C) ou padrão posicional (B). Fonte: 308k puzzles Lichess via woodpecker. Temas: garfo, cravada, espeto, mate sufocado, sacrifício grego, etc.
3. **Position facts** (`position_facts`): 24 detectores em `position_facts.py` — peão isolado/passado/atrasado/dobrado, cadeia de peões, IQP, escudo de peões intacto/quebrado, par de bispos, par de bispos opostos, mobilidade extrema, peça presa, abertura/fechamento de centro. Cada fato traz casa específica e métricas auxiliares.

### Filtro de relevância

Excluído do universo analítico (mas mantido em win-rate histórico):
- `n_user_moves < 25` (early timeout/resign)
- `termination ∈ {abandoned}`
- `termination ∈ {timeout, resigned} AND plies < 30`

### Confiabilidade da amostra (`confidence_pct`)

`50%` × tamanho da amostra (satura em 50 partidas) + `30%` × profundidade do motor (satura em d18) + `20%` × cobertura ECO.

### Lances paradigmáticos (Seção 7 do PDF)

Por partida paradigmática (4 totais por relatório):
- **Vitória**: 2 lances do jogador com maior swing positivo + 1 lance do jogador com maior loss
- **Derrota**: 2 lances do jogador com maior loss + 1 lance do adversário com maior swing a favor dele
- Spread mínimo de 8 plies entre os 2 destacados
- Ordem cronológica sempre
- Cada um traz as 3 camadas (stockfish + tactical + facts)

---

## Pré-requisitos

```bash
brew install python@3.12 pango
python3.12 -m pip install --break-system-packages pandas jinja2 chess weasyprint pytest
```

(WeasyPrint precisa de Pango via brew. Pandas, jinja2, chess e weasyprint via pip. pytest é opcional.)

## Setup inicial

**Não precisa rodar nenhum build.** As bases canônicas (`data/openings/eco.json` com 3.690 aberturas + `data/tactical/themes_index.json` com 308k puzzles processados) já vêm versionadas no repositório. Fresh-clone já é funcional.

O que é local apenas (gitignored):
- `data/history.db` — partidas + análises do user (criado na 1ª execução)
- `data-reports/` — relatórios PDF gerados
- `.app-state.json` + `.app-logs/` — lifecycle do app

### (Opcional) Rebuilds manuais

Só faça se quiser regenerar uma base do zero — em uso normal nunca é necessário:

```bash
# Reconstruir índice ECO a partir dos TSVs Lichess em data/openings/
python3.12 scripts/build_eco_index.py

# Reconstruir o índice tático (precisa baixar o release woodpecker primeiro)
python3.12 scripts/build_tactical_index.py \
  --source /tmp/woodpecker-data \
  --out data/tactical/themes_index.json \
  --min-count 3
```

## Fluxo canônico

```bash
# 1. Liga o app
bash scripts/start.sh         # ou /app-start

# 2. UI: configurar → Buscar Partidas → ⚙ Analisar Stockfish

# 3. Gerar PDF (via Claude Code)
/report-myself <username>
/report-enemy <username>

# 4. Desligar
bash scripts/stop.sh          # ou /app-stop
```

PDFs ficam em `data-reports/<user>_<perspective>_<stamp>.pdf`.

---

## Skills (slash commands)

| Comando | Função |
|---|---|
| `/app-start` | Liga o servidor local em background, registra PIDs, abre browser |
| `/app-stop` | Derruba todos os processos registrados |
| `/report-myself <user>` | PDF de diagnóstico próprio + plano de estudo (11 seções) |
| `/report-enemy <user>` | PDF de dossiê de combate (10 seções) |

---

## Testes

```bash
python3.12 -m pytest tests/ -v
```

Cobertura: helpers de score (calibração, faixas, monotonicidade), classificação de erros, SQLite history (insert, idempotência, ordem cronológica), cache de posições.

---

## Persistência longitudinal

Cada execução de `compute.py` grava snapshot completo em `analyses(username, stamp, computed_json)`. Permite:
- `delta_vs_previous` automático (variação de Score, ACPL, win-rate entre ciclos)
- Comparação cross-jogador (queries SQL diretas no `data/history.db`)
- Reprocessar com template novo sem refazer Stockfish (tudo está em `analyses.computed_json`)

---

## Stack técnica

- **Frontend**: HTML/JS vanilla, `chess.js@0.10.3`, `stockfish.js@10.0.2` (WASM)
- **Backend (CLI)**: Python 3.12, `pandas`, `python-chess`, `jinja2`, `weasyprint`
- **Servidor local**: stdlib `http.server` (sem deps externas)
- **Persistência**: SQLite (zero-config, single-file)
- **Bases externas**: Chess.com API (CC0), Lichess ECO (CC0), Lichess puzzles via woodpecker (CC0)
- **Renderização**: WeasyPrint (HTML+CSS → PDF), `chess.svg` (tabuleiros)

---

## Próximos passos

Ver [`ROADMAP.md`](ROADMAP.md).

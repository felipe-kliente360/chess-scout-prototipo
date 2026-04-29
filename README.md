# chess-scout-prototipo

Gerador de relatórios analíticos de xadrez (PDF, PT-BR) para jogadores de Chess.com. Coleta partidas, analisa cada lance com **Stockfish + tema tático + fatos estruturais** (3 camadas determinísticas e complementares), persiste tudo em SQLite local e produz dois tipos de dossiê:

- **`/report-myself`** — perspectiva "este jogador sou eu". Diagnóstico próprio + plano de estudo de 30 dias.
- **`/report-enemy`** — perspectiva "este é meu adversário". Plano de combate concreto.

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
| **Score por lance** | Accuracy 0–100% absoluta | **4 variantes de Score 0–10** calibrados por rating + depth: geral, competitivo (±10% Elo), ponderado (gaussiana de gap), média por modalidade. Inclui faixa de incerteza por depth (±0.2 a ±1.5). |
| **Análise por posição** | Só Stockfish | **3 camadas independentes**: Stockfish + tema tático (308k puzzles do woodpecker) + 24 fatos estruturais determinísticos |
| **Filtragem** | Inclui tudo | Filtro de relevância (descarta curtas, abandonos, early timeout/resign) — universo analítico vs. histórico real separados |
| **Aberturas** | Identifica ECO | Mapeia repertório completo + identifica weak spots + recomenda trocas concretas |
| **Lances paradigmáticos** | Mostra blunders | **Vitória**: 2 melhores + 1 pior do jogador. **Derrota**: 2 piores do jogador + 1 melhor do adversário. Spread temporal mínimo (8 plies), ordem cronológica. |
| **Plano de ação** | Genérico | Prescrições priorizadas por retorno/esforço + programa de puzzles |
| **Persistência** | Histórico no site | **SQLite local** com `players` + `analyses` + `games` + `game_analyses` + `position_cache` + posição cacheada de fatos estruturais |
| **Pipeline** | Web only | **Servidor Python local** elimina CSV manual; dedup automático por `(game_id, ply, depth)` — re-análises instantâneas |
| **Linguagem** | Inglês técnico | **PT-BR direto** (proibidas referências a "Stockfish", "ACPL", "centipeão" no texto final) |

---

## Como tudo funciona — visão de alto nível

### 1. Setup (uma vez por sessão)

```bash
python3.12 scripts/serve.py
```

Sobe um servidor stdlib em `http://127.0.0.1:8000/`. Sem dependências externas além do Python (Flask **não** é necessário). Esse servidor expõe:
- A UI estática (`index.html`)
- API REST sobre `data/history.db`

### 2. Configuração na UI

Abrir **http://127.0.0.1:8000/** no navegador (badge verde fixo `SERVER MODE · history.db` confirma o modo). Define:

- **Username** chess.com
- **Quantidade** partidas/formato — cap automático: `qtd × n_formatos ≤ 400`
- **Depth Stockfish** — default **15** (recomendado); hint dinâmico exibe ±incerteza por depth (±1.5 em d10, ±0.5 em d15, ±0.2 em d18+)
- **Engine** — Stockfish local WASM (Hash 256MB) ou API remota
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

**Loop por lance** — três camadas em paralelo, sem sobreposição:

1. **Stockfish** — `evaluation`, `mate`, `best_move`, `continuation`. Dedup hierárquico: se já tem em `game_analyses` com depth ≥ alvo, **reusa direto**; senão consulta `position_cache.json`; senão chama o engine.

2. **Tema tático** — `TacticalThemes.classifyPosition(fen, best, played)` consulta `themes_index.json` (4 MB, 32k fingerprints B + 2.5k C) construído a partir de **308k puzzles** do release [woodpecker-puzzles](https://github.com/felipe-kliente360/woodpecker-puzzles). Retorna `{theme, confidence, source}`.

3. **Fatos estruturais** — *roda no Python depois* (compute.py), nos lances com `loss_cp ≥ 50`. 24 detectores determinísticos puros que extraem geometria da posição: peão isolado, peão passado, escudo de peões, par de bispos, mobilidade extrema, etc. Cada fato vem com casa específica e métricas auxiliares.

**Persistência ao terminar cada partida** (não a cada N lances): `POST /api/analyses` em batch. UPSERT segue regra "maior depth vence" — d15 sobrescreve d10, d8 não sobrescreve d15.

### 5. Compute do relatório

```bash
python3.12 .claude/skills/_chess_shared/compute.py <username> --from-db
```

Lê `games + game_analyses` direto do SQLite, sem CSV. Produz `<user>_<stamp>_computed.json` com:

- **4 variantes de Score**: geral, competitivo (±max(150, 10% rating) Elo), ponderado (peso `exp(-(gap/300)²)`), média por modalidade (com spread como diagnóstico)
- **Banda de incerteza** por depth — texto deve relatar como faixa, não ponto
- **Por fase / cor / time_class / família ECO**
- **Aberturas weak spots** (n≥5 e win-rate <40%)
- **Tactical themes top** + correlação por resultado
- **Position facts top** + correlação (com cache delta no DB para próximas execuções)
- **4 partidas paradigmáticas** (2 melhores vitórias + 2 piores derrotas) com 3 `key_positions` cada

**Critério novo de paradigmáticas**:
- Vitórias → 2 lances do jogador com maior swing positivo + 1 lance do jogador com maior loss
- Derrotas → 2 lances do jogador com maior loss + 1 lance do adversário com maior swing contra o jogador
- Spread mínimo de 8 plies entre os 2 destacados (anti-cascata)
- Fallback se vitória "fácil" (sem swing ≥50 do jogador)
- Ordem cronológica sempre

Cada `key_position` carrega as 3 camadas juntas: stockfish + tactical_theme + position_facts.

### 6. Skill — PDF

```
/report-myself <user>     # ou /report-enemy <user>
```

A skill lê o computed JSON + `theory.md` (referência teórica), redige seções em PT-BR direto citando motivos pelo nome canônico (garfo, IQP, escudo quebrado, etc.) ancorados em autores (Capablanca, Nimzowitsch, Soltis, Vukovic, Dvoretsky). `build.py` renderiza HTML + WeasyPrint → **PDF final** em `data/<user>/<user>_<stamp>_<perspective>_report/`.

### 7. Re-análises são instantâneas

- Coletar partidas: `games` faz UPSERT idempotente — re-coletar não duplica.
- Re-analisar com mesma depth: dedup pula 100% do Stockfish.
- Subir depth (15 → 18): só re-roda nas plies onde a depth nova > existente.
- Position facts: cacheados no DB após primeira execução de `compute --from-db`.
- Tactical themes: classificação pura no browser, instantânea.

---

## Arquitetura

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (http://127.0.0.1:8000/)                           │
│  • chess.js + stockfish.js (WASM Hash 256MB)                │
│  • tactical-themes.js (consulta themes_index.json)          │
│  • Carrega ECO + position_cache lazy                        │
└────────────────┬────────────────────────────────────────────┘
                 │  REST API (/api/games, /api/analyses, ...)
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  scripts/serve.py (stdlib http.server)                      │
│  • UPSERT idempotente em games + game_analyses              │
│  • Filtra por game_ids para payload enxuto                  │
│  • Endpoints de dedup, summary, players                     │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  data/history.db (SQLite, ~12MB hoje)                       │
│  ├── players (usuários conhecidos)                          │
│  ├── games (partidas coletadas, UPSERT por URL)             │
│  ├── game_analyses (lances; PK game_id+ply; +position_facts)│
│  ├── analyses (snapshot do compute por (user, stamp))       │
│  └── position_cache (cache compartilhado por FEN)           │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  compute.py --from-db <user>                                │
│  • Score (4 variantes) + faixa de incerteza                 │
│  • Position_facts in-flight com cache delta no DB           │
│  • Aggregados táticos + estruturais com win-rate            │
│  • Paradigmáticas: 2 melhores + 1 pior (vitória),           │
│                    2 piores + 1 advers. (derrota)           │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────────────────┐
│  Skill (Claude Code)                                        │
│  • Redige sections.json em PT-BR (theory.md guia tom)       │
│  • build.py: Jinja2 + python-chess SVG + WeasyPrint         │
└────────────────┬────────────────────────────────────────────┘
                 │
                 ▼
       data/<user>/<user>_<stamp>_<perspective>_report/
              ├── *.pdf
              ├── computed.json
              └── sections.json
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
├── data/
│   ├── history.db                        # SQLite — fonte única de verdade
│   ├── openings/
│   │   ├── eco.json                      # Base ECO Lichess (3.690 posições)
│   │   └── position_cache.json           # Cache exportado para o browser
│   ├── tactical/
│   │   └── themes_index.json             # Índice tático (4 MB, do woodpecker)
│   └── <user>/<stamp>_*_report/          # Relatórios arquivados
│
├── scripts/
│   ├── serve.py                          # Servidor local (stdlib)
│   ├── build_eco_index.py                # Constrói eco.json
│   ├── build_position_cache.py           # Backfill cache
│   ├── build_tactical_index.py           # Constrói themes_index.json
│   ├── import_csv_to_db.py               # Migration CSV legado → SQLite
│   ├── export_cache.py
│   └── ... (outros utilitários)
│
├── tests/
│   ├── conftest.py
│   ├── test_helpers.py                   # Score, depth_factor, classify_loss…
│   └── test_history.py                   # SQLite + cache de posições
│
└── .claude/
    ├── settings.json
    ├── commands/
    │   ├── report-myself.md
    │   └── report-enemy.md
    └── skills/
        ├── _chess_shared/
        │   ├── compute.py                # Pipeline analítico (1300+ linhas)
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

### Score 0–10 (4 variantes calibradas)

Performance vs. expectativa para o seu rating, **não** acurácia absoluta:

```
score = 10 * exp(-(acpl_d20 / acpl_esperado_para_o_rating) / 2)
```

| Variante | Quando usar |
|---|---|
| **`score_10_by_modality_avg`** | **Canônico**. Média aritmética dos competitivos por time_class — neutraliza farming/uso de motor em formato específico. |
| `score_10_competitive` | Subset com adversários em ±max(150, 10% rating) Elo |
| `score_10_weighted` | Todas as partidas, peso `exp(-(gap/300)²)` por gap de Elo |
| `score_10_overall` | Auditoria — todas as partidas sem filtro |

**Spread por modalidade ≥2.0** dispara warning: indica regimes de jogo distintos (Daily com motor vs Blitz humano), narrativa deve separar por formato.

### Faixa de incerteza por depth

| Depth | Banda | Leitura |
|---|---|---|
| ≤10 | ±1.5 | Preview — só erros grosseiros |
| 12 | ±1.0 | Rápido, magnitude duvidosa |
| **15** | **±0.5** | **Padrão recomendado** |
| 18+ | ±0.2 | Análise séria |

### As 3 camadas de análise por posição

1. **Stockfish**: avaliação numérica, melhor lance, mate.
2. **Tactical theme** (`tactical_theme`, `tactical_confidence`, `tactical_source`): classificação automática via fingerprint de delta (best vs played) ou padrão posicional. Fonte: 308k puzzles Lichess filtrados por qualidade no woodpecker-puzzles. Temas: garfo, cravada, espeto, mate sufocado, sacrifício grego, etc.
3. **Position facts** (`position_facts`): 24 detectores em `position_facts.py` — peão isolado/passado/atrasado/dobrado, cadeia de peões, IQP, escudo de peões intacto/quebrado, par de bispos, par de bispos opostos, mobilidade extrema, peça presa, abertura/fechamento de centro. Cada fato traz casa específica e métricas auxiliares.

### Filtro de relevância

Excluído do universo analítico (mas mantido em win-rate histórico):
- `n_user_moves < 25` (early timeout/resign)
- `termination ∈ {abandoned}`
- `termination ∈ {timeout, resigned} AND plies < 30`

### Confiabilidade da amostra (`confidence_pct`)

`50%` × tamanho da amostra (satura em 50 partidas) + `30%` × profundidade do motor (satura em d18) + `20%` × cobertura ECO.

### Lances paradigmáticos (Seção 7)

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

## Setup inicial (uma vez por máquina)

```bash
# 1. Construir índice ECO (3.690 aberturas indexadas)
python3.12 scripts/build_eco_index.py

# 2. Backfill do cache de posições (se já houver CSVs em data/)
python3.12 scripts/build_position_cache.py
python3.12 scripts/export_cache.py

# 3. Construir índice tático (a partir do woodpecker release; uma única vez)
python3.12 scripts/build_tactical_index.py \
  --source /tmp/woodpecker-data \
  --out data/tactical/themes_index.json \
  --min-count 3
```

## Fluxo canônico hoje

```bash
# Terminal 1 — deixar rodando
python3.12 scripts/serve.py
```

Browser → http://127.0.0.1:8000/ → configurar → "Buscar Partidas" → "⚙ Analisar Stockfish".

```bash
# Terminal 2 — gerar relatório
/report-myself <username>     # via Claude Code
```

A skill chama `compute.py <user> --from-db` e `build.py <user> myself` automaticamente.

## Modo legado (CSV)

Funciona como fallback quando `history.db` está vazio para o user. Abrir `index.html` direto via `file://` exibe badge cinza `FILE MODE · CSV`. Os CSVs são baixados manualmente, copiados para `data/`, e o `compute.py` roda **sem** `--from-db`. Suportado mas não recomendado.

---

## Skills (slash commands)

| Comando | Skill | Output |
|---|---|---|
| `/report-myself <user>` | `report-myself` | PDF, plano de estudo, 11 seções |
| `/report-enemy <user>` | `report-enemy` | PDF, plano de combate, 10 seções |

Ambos compartilham `compute.py` — diferem em template e voz do redator.

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

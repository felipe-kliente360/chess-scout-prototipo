# chess-scout-prototipo

Gerador de relatórios analíticos de xadrez (PDF, PT-BR) para jogadores de Chess.com. Coleta partidas, analisa cada lance com Stockfish, classifica aberturas com a base ECO do Lichess, e produz dois tipos de dossiê:

- **`/report-myself`** — perspectiva "este jogador sou eu". Diagnóstico próprio + plano de estudo de 30 dias.
- **`/report-enemy`** — perspectiva "este é meu adversário". Plano de combate concreto para vencê-lo.

---

## Por que existe

Análises padrão do Chess.com e Lichess respondem "o que aconteceu nesta partida?". Este projeto responde "**o que precisa ser estudado para o próximo mês?**" e "**como devo me preparar para enfrentar este oponente específico?**" — duas perguntas que ferramentas comerciais não atendem com profundidade.

## Diferenciais

| Item | Chess.com / Lichess | Este projeto |
|---|---|---|
| **Score por lance** | Accuracy 0–100% absoluta | **Score 0–10 calibrado por rating + depth** — baseline 6 = "jogou como esperado" |
| **Filtragem** | Inclui todas as partidas | **Filtro de relevância**: exclui curtas, abandonos, early timeout (universo analítico vs. histórico real separados) |
| **Aberturas** | Identifica ECO, sem profundidade narrativa | **Mapeia repertório completo** + identifica weak spots + recomenda trocas concretas |
| **Lances paradigmáticos** | Mostra blunders maiores | **Lances decisivos (eval swing)** — funciona tanto em vitórias clean quanto em derrotas; setas vermelha (jogado) e verde (melhor) |
| **Plano de ação** | Genérico ("estude finais") | **Prescrições priorizadas por retorno/esforço** + programa de puzzles consumível por app externo |
| **Persistência** | Histórico isolado no site | **SQLite local** com `players` + `analyses` para evolução temporal + comparativos cross-jogador |
| **Cache** | N/A | **Cache de posições por FEN+depth** — re-coletas 60–80% mais rápidas |
| **Linguagem** | Inglês, técnico | **PT-BR direto e acessível** (proibidas referências a "Stockfish", "ACPL", "centipeão" no relatório final) |

## Para quem é

- **Jogador sério** que quer saber o que estudar a seguir, não só o que errou.
- **Treinador** que precisa de relatório técnico para mostrar evolução do aluno.
- **Competidor** que vai enfrentar adversário conhecido e quer dossiê pré-jogo.

---

## Como usar

### Pré-requisitos (uma vez)

```bash
brew install python@3.12 pango
python3.12 -m pip install --break-system-packages pandas jinja2 chess weasyprint pytest
```

### Setup inicial (uma vez por máquina)

```bash
# Construir índice ECO (3.690 aberturas indexadas)
/opt/homebrew/bin/python3.12 scripts/build_eco_index.py

# Backfill do cache de posições (se já houver CSVs em data/)
/opt/homebrew/bin/python3.12 scripts/build_position_cache.py

# Exportar cache como JSON para o browser consumir
/opt/homebrew/bin/python3.12 scripts/export_cache.py
```

### Fluxo completo de um relatório

#### 1. Coleta + análise (browser)

Abrir `index.html` no Chrome/Firefox. Configurar:
- **Username** Chess.com (ex: `jhoumedeiros`)
- **Quantidade** de partidas (50 até 500)
- **Depth** Stockfish (default 18 — recomendado)
- **Engine**: local WASM (default) ou API remota stockfish.online
- **Ritmos** a incluir: bullet, blitz, rapid, daily

Clicar em **"Buscar partidas"** → o browser:
- Baixa partidas via Chess.com API
- Filtra por ritmo selecionado e ≥15 lances
- Classifica aberturas via base ECO carregada localmente

Clicar em **"Analisar Stockfish"** → o browser:
- Carrega o cache de posições local (`position_cache.json`)
- Para cada FEN, checa cache antes de chamar Stockfish (hit-rate típico: 30–80%)
- Análises novas são adicionadas ao CSV final

Baixar os 2 CSVs gerados:
- `<username>_<timestamp>_games_<N>.csv`
- `<username>_<timestamp>_analysis_d<N>.csv`

#### 2. Mover CSVs para `data/` raiz

```bash
mv ~/Downloads/jhoumedeiros_*.csv data/
```

#### 3. Atualizar cache (opcional mas recomendado)

```bash
/opt/homebrew/bin/python3.12 scripts/import_new_analysis.py data/<username>_<stamp>_analysis_d<N>.csv
```

#### 4. (Opcional) Filtrar partidas curtas residuais

```bash
/opt/homebrew/bin/python3.12 scripts/filter_short_games.py \
  data/<username>_<stamp>_games_<N>.csv \
  data/<username>_<stamp>_analysis_d<N>.csv
```

#### 5. Gerar relatório

Dentro do Claude Code:

```
/report-myself <username>
```

ou

```
/report-enemy <username>
```

A skill:
1. Roda `compute.py` → gera `<username>_<stamp>_computed.json` + grava no SQLite history.
2. Lê o JSON, redige as ~12 seções narrativas → `<username>_<stamp>_<perspective>_sections.json`.
3. Roda `build.py` → renderiza PDF, move tudo para `data/<username>/<username>_<stamp>_<perspective>_report/`, deixa `data/` raiz limpa.

**Output:** `data/<username>/<username>_<stamp>_<perspective>_report/<username>_<stamp>_<perspective>_report.pdf`

---

## Arquitetura

```
┌──────────────────────────┐
│ index.html (browser)     │
│  • Chess.com API         │
│  • Stockfish.js (WASM)   │
│  • ECO + position cache  │
└───────────┬──────────────┘
            │ baixa 2 CSVs
            ▼
┌──────────────────────────┐
│ data/ (raiz)             │  ← área de trabalho temporária
│  • games_*.csv           │
│  • analysis_*.csv        │
└───────────┬──────────────┘
            │
   ┌────────┴─────────┐
   │                  │
   ▼                  ▼
┌──────────┐    ┌──────────────────┐
│compute.py│───▶│  history.db      │
│          │    │  (SQLite)        │
│  KPIs +  │    │  • players       │
│  score   │    │  • analyses      │
│  + cal.  │    │  • position_cache│
└────┬─────┘    └──────────────────┘
     │
     ▼
┌──────────────────────────┐
│ <stamp>_computed.json    │  ← dados estruturados
└────┬─────────────────────┘
     │  + sections JSON (redator)
     ▼
┌──────────────────────────┐
│ build.py                 │
│  • Jinja2 template       │
│  • python-chess SVG      │
│  • WeasyPrint            │
└────┬─────────────────────┘
     │
     ▼
┌──────────────────────────┐
│ data/<user>/<stamp>_     │  ← arquivado, data/ raiz fica limpa
│ <perspective>_report/    │
│  • PDF                   │
│  • computed.json         │
│  • sections.json         │
│  • CSVs originais        │
└──────────────────────────┘
```

## Estrutura do projeto

```
chess-scout-prototipo/
├── index.html                            # Coletor + analisador (browser)
├── README.md                             # Este arquivo
├── ROADMAP.md                            # Plano de evolução
│
├── data/                                 # Outputs (gitignore recomendado)
│   ├── history.db                        # SQLite (players + analyses + cache)
│   ├── openings/
│   │   ├── eco.json                      # Base ECO Lichess (3.690 entries)
│   │   └── position_cache.json           # Cache exportado para o browser
│   └── <username>/<stamp>_*_report/      # Relatórios arquivados
│
├── scripts/                              # CLIs auxiliares
│   ├── build_eco_index.py                # Constrói eco.json a partir dos TSVs Lichess
│   ├── build_position_cache.py           # Backfill do cache via CSVs existentes
│   ├── export_cache.py                   # Exporta cache p/ o browser consumir
│   ├── import_new_analysis.py            # Adiciona novas posições ao cache
│   ├── enrich_eco.py                     # Adiciona colunas ECO a um games.csv
│   └── filter_short_games.py             # Filtra partidas com <15 lances
│
├── tests/                                # pytest (55 testes)
│   ├── conftest.py
│   ├── test_helpers.py                   # Score, depth_factor, classify_loss…
│   └── test_history.py                   # SQLite + cache de posições
│
└── .claude/
    ├── settings.json                     # Allowlist de comandos
    ├── commands/                         # Slash commands
    │   ├── report-myself.md
    │   └── report-enemy.md
    └── skills/
        ├── _chess_shared/                # Código compartilhado
        │   ├── compute.py                # Pipeline analítico
        │   ├── build.py                  # Renderização PDF
        │   ├── history.py                # SQLite + cache helpers
        │   ├── theory.md                 # Referência conceitual p/ redação
        │   ├── base.css                  # CSS compartilhado
        │   └── macros.html               # Macros Jinja compartilhados
        ├── report-myself/
        │   ├── SKILL.md                  # Instruções de redação (myself)
        │   └── template.html             # Template específico (verde)
        └── report-enemy/
            ├── SKILL.md                  # Instruções de redação (enemy)
            └── template.html             # Template específico (vermelho)
```

---

## Conceitos centrais

### Score 0–10 (calibrado)

Não é uma medida absoluta de qualidade — é **performance vs. expectativa para o seu rating**:

```
score = 10 * exp(-(acpl_normalizado / acpl_esperado_para_o_rating) / 2)
```

| Score | Leitura |
|---|---|
| 9–10 | Muito acima do esperado (4×+ melhor que típico) |
| 7–9 | Acima do esperado |
| **5,5–6,5** | **Baseline — jogou como esperado** |
| 4–5,5 | Abaixo do esperado |
| < 4 | Bem abaixo |

### Confiabilidade da amostra (`confidence_pct`)

Combina três fatores:
- **50%** = tamanho da amostra (satura em 50 partidas relevantes)
- **30%** = profundidade do motor (satura em depth 18)
- **20%** = cobertura ECO (% de partidas com abertura mapeada)

### Filtro de relevância

Aplicado a TODAS as métricas analíticas:
- **n_user_moves ≥ 25** (exclui early timeout/resign)
- **termination ∉ {abandoned}** (exclui saídas sem jogar)
- **termination ∈ {timeout, resigned} AND plies < 30** → exclui (early)

Win-rate e contagens V/D/E continuam sobre o universo COMPLETO (histórico real do chess.com).

### Lances decisivos (Seção 7)

Para cada partida paradigmática, busca os **3 lances onde a posição mais virou** na direção do vencedor (`cp_after - cp_before`). Filtra os 8 primeiros plies (livro de abertura). Em partidas líquidas sem viradas reais, fallback distribuído (50%/75%/95% do percurso).

---

## Skills (slash commands)

| Comando | Skill | Output |
|---|---|---|
| `/report-myself <user>` | `report-myself` | PDF verde, plano de estudo, 13 seções |
| `/report-enemy <user>` | `report-enemy` | PDF vermelho, plano de combate, 12 seções |

Ambos compartilham o mesmo `compute.py` — só diferem em template e na voz do redator.

---

## Testes

```bash
/opt/homebrew/bin/python3.12 -m pytest tests/ -v
```

55 testes cobrindo:
- Helpers de score (calibração, faixas, monotonicidade)
- Classificação de erros (blunder/mistake/inaccuracy)
- SQLite history (insert, idempotência, ordem cronológica)
- Cache de posições (hit/miss, depth-aware, FEN canonicalização)

---

## Próximos passos

Ver [`ROADMAP.md`](ROADMAP.md) — inclui prioridades por modelo de produto (B2C/B2B/interno) e tradeoffs de cada iteração.

---

## Stack técnica

- **Frontend**: HTML/JS vanilla, `chess.js`, `stockfish.js` (WASM)
- **Backend (CLI)**: Python 3.12, `pandas`, `python-chess`, `jinja2`, `weasyprint`
- **Persistência**: SQLite (zero-config, single-file)
- **Bases externas**: Chess.com API (CC0), Lichess ECO openings (CC0)
- **Renderização**: WeasyPrint (HTML+CSS → PDF), `chess.svg` (tabuleiros)

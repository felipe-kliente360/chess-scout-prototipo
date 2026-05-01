# Roadmap — chess-scout-prototipo

Histórico das decisões de design + próximos passos pendentes. Vivente: atualizar a cada ciclo de evolução.

---

## ✅ Entregue (até 2026-04-29)

### Coleta e análise

- Coleta via Chess.com API direto no browser, com filtros de ritmo (bullet/blitz/rapid/daily) e contagem mínima de plies (≥15).
- Stockfish.js depth 15 (default novo) com handshake `isready/readyok` e `setoption Hash 256MB`.
- Validação UCI: `best_move` retornado pelo motor é checado contra a posição via `chess.js`; se ilegal, vira string vazia.
- Classificação de aberturas via base ECO Lichess (3.690 posições EPD-indexadas).
- **Cache de posições**: `position_cache.json` (compartilhado entre users) + `game_analyses` no SQLite (por user).
- Cap de 400 partidas total + warning quando estimativa >30 min.

### 3 camadas de análise por posição (Stockfish + tática + estratégia)

- **Tema tático automático** via fingerprint (woodpecker puzzles, 308k Lichess CC0). Implementado em `tactical-themes.js` (browser) + `scripts/build_tactical_index.py` (build). Índice: 32815 fingerprints B (posicional) + 2552 C (delta best vs played), 4 MB / 441 KB gzip.
- **Fatos estruturais determinísticos** via `position_facts.py`: 24 detectores cobrindo estrutura de peões, colunas/diagonais, segurança do rei, material, caráter da posição. Roda em todo lance com `loss_cp ≥ 50`, com cache delta no DB.
- **Análise de tempo (relógio)** via `clock.py` + backfill em `history.py`. Extrai `[%clk]` dos PGNs, popula `game_analyses.clock_ms`/`time_spent_ms`. `compute_time_analysis` em `compute.py` produz: tempo por fase, distribuição por bucket de velocidade, pressão de relógio (clock <10% do orçamento) com blunder rate inside/outside, top "pensou e errou" e "errou rápido". Renderizado como Seção 9 nos relatórios myself/enemy. Daily/correspondência ignorado.

### Pipeline SQLite (substitui CSV manual)

- Schema completo: `players`, `analyses` (snapshot por ciclo), `games`, `game_analyses` (PK game_id+ply, retenção da maior depth), `position_cache`. Coluna `position_facts` com migration via PRAGMA.
- `scripts/serve.py` — servidor stdlib (sem Flask), API REST sobre o DB.
- Browser auto-detecta `SERVER MODE`; persistência por partida (não a cada N lances); dedup via `?game_ids=...`.
- `compute.py <user>` lê direto do SQLite (CSV completamente descontinuado em `13ce2e1`).
- `scripts/import_csv_to_db.py` — migration one-shot do legado.

### Score 0–10 (recalibração final 2026-04-29)

- **Curva ACPL chess.com empírica** (não a teórica antiga): âncoras 1000:120, 1400:80, 1800:50, 2200:30, 2500:20.
- **Blend ponderado**: 50% ACPL relativo + 30% win-rate + 20% redução de blunders (só blunders ≥300cp).
- **Penalidade de motor**: ratio < 0.5 desconta o Score até piso 0.5 (sinaliza ACPL implausível para o rating).
- **`kpis.score_10` canônico (Opção B)**: hierarquia `competitive (n≥15)` → `modality_avg (≥2 modalidades)` → `overall`. `score_10_basis` documenta a base escolhida.
- 4 variantes calculadas (overall/competitive/weighted/modality_avg) + spread por modalidade + faixa de incerteza por depth (±0.2 a ±1.5).
- Validação nos 3 casos extremos: LucasCamilo10 (farming) 3.2, jhoumedeiros (Daily com motor) 4.5, miguelrov (1424 honesto) 5.4.

### Análise (compute.py)

- **Filtro de relevância** aplicado ao universo analítico: ≥25 lances, sem `abandoned`/early `timeout`/`resigned`. Win-rate continua sobre universo completo.
- **Confiabilidade da amostra** (`confidence_pct`) ponderada: 50% amostra + 30% depth + 20% cobertura ECO.
- **Programa de puzzles** auto-derivado do perfil + faixa de rating.
- **Persistência longitudinal**: `players` + `analyses` no SQLite com snapshot completo. `delta_vs_previous` automático.

### Relatórios (build.py + templates)

- Duas perspectivas: `/report-myself` (verde, plano de estudo, 11 seções) e `/report-enemy` (vermelho, plano de combate, 10 seções).
- Templates compartilham `_chess_shared/base.css` + `macros.html`.
- **Paradigmáticas reformuladas**: vitória → 2 melhores + 1 pior do jogador; derrota → 2 piores + 1 melhor do adversário. Spread mínimo 8 plies entre os 2 destacados, ordem cronológica.
- Cada `key_position` carrega as 3 camadas juntas (Stockfish + tactical_theme + position_facts).
- Notação SAN limpa, legenda de score, header com confiabilidade %, mensagens de filtro em linguagem natural.

### Performance

- Index `(game_id, depth)` em `game_analyses` — escala para 200k+ lances.
- Stockfish WASM com Hash 256MB (10–20% mais rápido em finais com transposições).
- Flush por partida (não batch 80) — alinha unidade de persistência com unidade lógica.
- Filtro `?game_ids=...` em `/api/analyses` — payload proporcional à sessão atual.

### Skill `report-coach` (3ª perspectiva, B2B)

- **Voz "treinador → aluno"**: diagnóstico do aluno + delta vs ciclo anterior + comparativo cross-aluno + plano didático prescritivo (livro/capítulo + cronograma + métrica para próxima aula).
- Template em verde-azulado (`--accent: #1d6e8e`), 12 seções; benchmark cross-aluno renderizado em tabela com aluno destacado.
- `compute_coach_benchmarks` em `build.py` calcula percentil do aluno em Score, win-rate, confiança e profundidade ECO sobre todos os players da DB. Disponível só para `perspective=coach`.
- Slash command `/report-coach <username>`. Skill seguida do mesmo padrão de `myself`/`enemy` (compute → cache lookup → redação → build).

### Cache de sections (regen rápida + economia de tokens)

- Tabela `sections_cache (username, perspective, stamp, sections_json, signature_json)` no SQLite.
- `compute_sample_signature` extrai assinatura compacta da amostra (n_games, score_10, fases, top openings, tactical, paradigmáticas, time_median).
- `signature_delta_flags` compara assinatura cacheada vs atual e devolve flag por seção (`reuse` | `regenerate`) com heurísticas: n_games delta >20% regenera tudo; score delta >0.5 regenera 1/2/6/9/11; fase delta >0.3 regenera 2/6; top_openings/tactical_top1/paradigmaticas mudaram regeneram a respectiva seção.
- CLI `cache_lookup.py <user> <perspective>` retorna `{cached, sections, delta_flags, reuse_recommendation}`. Skills `report-myself`/`report-enemy`/`report-coach` consultam antes de redigir; em `partial_regen` regeneram só seções com flag, copiam o resto. Economia ~10× em tokens quando muda pouco.

### Backend Stockfish nativo + fila

- Tabela `analysis_queue (id, username, game_id, target_depth, status, ...)` com índices em status+enqueued_at e username+status.
- Worker em `scripts/analyze_worker.py` — `chess.engine.SimpleEngine.popen_uci(stockfish)`, `Hash=256`, `Threads=1`, multiprocessing N workers em paralelo. Modo `--once` para esvaziar fila e sair, ou loop infinito padrão.
- Endpoint `POST /api/analyze/queue` (browser enfileira) + `GET /api/analyze/progress` (polling de progresso). Helpers `enqueue_games_for_analysis` / `claim_next_pending` (atomic UPDATE + RETURNING) / `mark_job_done` / `queue_progress` em `history.py`.
- UI: botão "⚡ Enfileirar no backend (Stockfish nativo)" lê pendentes via `/api/analyses/needed`, posta lista, faz polling a cada 3s até zerar pending+running.
- Smoke validado end-to-end: 1 partida com depth 20 (45 lances) processada pelo worker em <1 minuto.

### Redactor automático com prompt caching

- `redactor_prompt.md` (~6k chars) + `theory.md` (~49k chars) + `SKILL.md` da perspectiva (~11k chars) entram em 3 blocos `cache_control: ephemeral` no system prompt da API Anthropic. Total cacheável ~16k tokens; variável (computed.json) ~3k tokens.
- `redactor.py <username> <perspective> [--model claude-opus-4-7]` — devolve sections.json em `data/`. Logs cache_read/cache_create por chamada.
- Flag `--auto-redact` em `build.py`: gera sections.json e segue para construção de PDF sem precisar de Claude na conversa.
- Pré-requisito: `ANTHROPIC_API_KEY` no env. Custo unitário esperado: ~R$ 0,54 com cache hit (vs R$ 1,08 sem otim).

### Anti-cheat indireto via outliers de Score

- `compute_cheat_signals` em `compute.py` — 4 sinais: performance vs rating esperado (ratio acpl_d20/expected), consistência entre formatos, distribuição de tempo por bucket, variação por fase.
- Cada sinal vira semáforo `green` | `yellow` | `red` com nota explicativa. Overall = pior dos 4 (ou yellow se ≥2 yellows).
- Macro `cheat_signals_block` em `macros.html` renderiza tabela colorida com disclaimer ("não constitui prova"). Seção opcional 13 nos templates myself e enemy — só renderiza se `available=true`.
- Tom factual por default; redator pode escrever 1 parágrafo opcional em `section_cheat_signals` quando overall != green.

### Separar coleta vs análise (estado persistente do DB)

- Painel "DB state" embaixo da estimativa: ao trocar username/depth, mostra "X partidas no DB · Y precisam análise em depth Z".
- Botão "⚙ Analisar pendentes (sem refetch)" que carrega games existentes via `/api/games`, filtra pelos formatos selecionados e dispara `analyzeGames()` reusando todo cache do DB.
- `renderPreview` extraído como função reutilizável; `refreshDbState` chamado após fetch / analyze / reset.

### Coleta — toggle de cota + detecção de tendência *(substituído em 2026-05-01)*

- **Modo de cota** (`QUOTA_MODE`): radio "por estilo" vs "total (recência)". *(Substituído: opção única "total por recência" — ver "Simplificação de parâmetros" abaixo.)*
- **Pré-get de tendência** (`fetchProfileTrend`): puxava últimos 60 dias do perfil chess.com. *(Removido por complexidade sem retorno proporcional.)*

### Telemetria de execução (recalibração da estimativa)

- Tabela `execution_logs (id, username, started_at, ended_at, duration_seconds, depth, engine, n_games, n_positions_total, n_positions_analyzed, n_db_hits, n_cache_hits, n_cache_misses, n_failures, expected_seconds_at_start, status)`.
- `index.html` chama `POST /api/execution-logs/start` ao iniciar análise e `/end` no `finally`. Estimativa fica em `expected_seconds_at_start`; tempo real entra em `duration_seconds`.
- `GET /api/execution-logs/calibration?engine=...` retorna mediana de `sec/posição` por `(engine, depth)` (mínimo 3 amostras). Browser carrega no boot e em `estimateSecondsPerPosition` usa o valor observado quando disponível, fallback no modelo empírico antigo. Recalibra automaticamente sem ajuste manual.

### Lifecycle e output (commits `397956f`/`13ce2e1`)

- **Skills `/app-start` e `/app-stop`** + scripts `start.sh`/`stop.sh`. PIDs registrados em `.app-state.json`, idempotente, com fallback `pgrep` defensivo.
- **Output centralizado em `data-reports/`**: PDFs no formato `<user>_<perspective>_<stamp>.pdf`, sem subpastas. Computed.json e sections.json deletados após build (preservados em `analyses.computed_json`).
- **CSV legado completamente removido**: `find_latest_csvs` apagado, `--from-db` deixou de ser flag (vira default), botões CSV removidos da UI, modo FILE bloqueia operação com mensagem de instrução. Pipeline 100% via SQLite.
- **Dead code removido**: 5 scripts legados (`build_position_cache`, `enrich_eco`, `export_cache`, `filter_short_games`, `import_new_analysis`), helper `dedup_map_for_user` + endpoint `/api/analyses/dedup-map`, import órfão de `shutil`.

### Qualidade

- 55 testes pytest (helpers de score, expected_acpl, depth_factor, classify_loss, phase_of_ply, history, position_cache).
- README reescrito com pipeline atual, arquitetura, conceitos centrais.
- 4 commits temáticos publicados em GitHub: `efb3e1a` (tactical), `1c9662c` (servidor), `2495e7c` (position_facts), `588735b` (consolidação SQLite + 3 camadas + scores + paradigmáticas), seguidos de fixes (`04609c5`, `8d8cb94`, `0ef1193`, `824d881`, `3efb4c6`, `1581037`).

---

---

## ✅ Entregue (2026-05-01)

### Simplificação de parâmetros de coleta

- Removidos: seletor de quantidade, radios de cota e checkboxes de modalidade.
- Substituído por toggle binário **rápida (30 partidas)** / **completa (100 partidas)**. Quantidades derivadas de significância estatística: 30 → ACPL ±14cp, win-rate ±18%, táticas + relógio direcionais; 100 → ACPL ±8cp, win-rate ±10%, ranking tático confiável, trend lines funcionais.
- Coleta sempre por recência, todos os formatos (bullet/blitz/rapid/daily), sem filtro de modalidade.
- `QUOTA_MODE = "total"` e `TIME_CLASSES = all` agora constantes não configuráveis. `fetchProfileTrend` removido.

### Confiança tática adaptativa (peso bullet por fallback)

- `_MIN_RB_FOR_BULLET_ZERO = 15`: se rapid+blitz ≥ 15, bullet tem peso 0.0 (comportamento original). Se rapid+blitz < 15, bullet recebe peso 0.4 como fallback para evitar amostra tática vazia.
- Daily sempre peso 0.0 (motor assistido — sem exceção).
- `tactical_confidence` adicionado ao payload de `compute.py`: `{level: "alta"|"média"|"baixa"|"insuficiente", n_rapid_blitz, n_bullet_used, weights_adapted, note}`. Nível função de n_rapid_blitz; se `weights_adapted=true`, note sinaliza dependência de bullet.
- UI exibe badge de cobertura tática após coleta (`logTacticalCoverage`).
- SKILL.md de todas as perspectivas atualizados com regras de exibição por nível (se `level ≠ "alta"` → nota obrigatória antes da narrativa tática; se `"insuficiente"` → pula temas).

### Fila de análise multi-jogador

- Painel **FILA DE ANÁLISE** na metade inferior do painel direito (flex-column: `#log` flex:1 + `#queue-panel` 220px fixo).
- Cada item mostra status colorido + `X/N posições (%)` em tempo real + barra de progresso + botões ⏸ pausa / ■ stop.
- Pausa salva `resumeFromGame` e passa execução para o próximo da fila; retoma exatamente do ponto salvo.
- Stop marca job como parado e preserva tudo já persistido no DB.
- Novo jogador entra no final da fila sem interromper análise em curso.
- `analyzeGames()` virou thin wrapper (`addToQueue()` → `processQueue()`); corpo real migrou para `runQueuedAnalysis(job)` que usa `job.games` (snapshot) e `job.username` — independente de globais.
- Flags `pauseFlag` e `stopFlag` verificadas a cada iteração de partida e posição — saída limpa sem terminação forçada.

---

## 🔜 Próximas iterações (em ordem de retorno comercial)

### 5. Comparativo cross-jogador
**Por quê:** o SQLite `players` table existe mas não é usado. Querível: "como o `jhoumedeiros` se compara aos outros usuários da minha base?".
**Como:** Nova seção opcional no relatório (myself only): tabela com percentil de score / win-rate / depth de teoria entre os players da DB.
**Custo:** 4h.

### 6. Suporte a Lichess (não só Chess.com)
**Por quê:** muitos jogadores sérios usam Lichess. API é aberta e tem PGN+análise embutida.
**Como:** Adicionar dropdown de "fonte" no `index.html`; novo parser `parseLichessGames`; resto do pipeline reaproveita.
**Custo:** 4h.

### 9. PWA + IndexedDB (cache no browser sem backend)
**Por quê:** se o browser cachear sozinho, dispensa o servidor local pra usuários casuais.
**Como:** Service worker que mantém `position_cache` em IndexedDB; sync periódico com SQLite via download/upload manual.
**Custo:** 1 dia. Trade-off: hoje o `serve.py` é stdlib e simples; PWA adiciona complexidade.

---

## ❓ Decisões estratégicas em aberto

### Modelo de produto
- **B2C** (jogador casual): prioridade 1 + 2 (backend + redação automática). Sem isso, custo unitário inviável.
- **B2B** (treinador/clube): prioridade 3 + 5 (perspectiva coach + comparativo cross-jogador).
- **Interno/amigos**: MVP atual já entrega; investir em 4 (telemetria) e 6 (Lichess).

### Modelo de cobrança (se B2C)
- Por relatório (R$ X cada).
- Assinatura mensal (1 relatório/mês incluído + cache acumulado).
- Freemium: 1 relatório grátis com sample reduzido, paga full.

#### Custo unitário estimado (LLM) — referência 2026-04-29

Medido com LucasCamilo10 (100 partidas analisadas, depth 15, computed_json 39 KB). Modelo Opus 4.7. USD/BRL = 5,40.

| Cenário | Input tok | Output tok | USD | BRL |
|---|---|---|---|---|
| 1 relatório sem otimização (estado atual) | 35k | 6k | $0.20 | **R$ 1,08** |
| 1 relatório com prompt caching (theory/SKILL/CLAUDE estáticos) | ~4k efetivos | 6k | $0.10 | **R$ 0,54** |
| 1 relatório + cache de sections.json (regenera só deltas; item #10 do roadmap) | ~4k | ~1k | $0.02–0.05 | **R$ 0,11–0,27** |
| **2 relatórios (myself + enemy)** sem otimização | 70k | 11k | $0.40 | **R$ 2,16** |
| **2 relatórios** com prompt caching | — | — | $0.20 | **R$ 1,08** |
| **2 relatórios** com caching + sections cache | — | — | $0.04–0.10 | **R$ 0,22–0,54** |

**Tempo de geração:** 2–4 min por relatório (Opus a ~40–60 tok/s gerando 5–7k output).
Compute.py + build.py somam ~10s e zero token.

**Implicações para go-to-market:**
- **Por relatório a R$ 5,00**: margem ≥80% mesmo sem otimização. Razoável pra início.
- **Assinatura mensal R$ 19,90 com 4 relatórios/mês**: COGS R$ 4,32 sem otimização, R$ 0,88 com tudo ligado → margem 78%–96%.
- **Freemium**: o primeiro relatório custa R$ 1,08–2,16 (myself + enemy combo); recuperável em ≥1 conversão a cada 5–10 free.
- **Custo de coleta + análise Stockfish**: zero LLM, mas exige browser aberto ~30 min em depth 15. Em backend nativo (item #1 do roadmap), cai pra ~3 min/user — viabiliza B2C.
- **Não esquecer**: cobertura ECO + base tactical fingerprints é CC0 (zero custo de licença). PGN do chess.com é grátis via API.

### Cobertura de motor
- Manter Stockfish 16 atual ou subir para 17 (já lançado, ~200 Elo a mais)?
- Considerar engine alternativo (Leela Chess Zero) para análise posicional/estratégica diferente.

---

## 🐛 Bugs/débitos técnicos abertos

- **Coverage de testes**: helpers cobertos, mas pipeline end-to-end (compute → JSON) não tem teste de integração com fixture pequena.
- **Sem CI**: testes rodam só local. Adicionar GitHub Actions com pytest seria o mínimo.
- **Drift entre `theory.md` e SKILL.md**: documentação de redação dispersa em 3 lugares (theory.md compartilhado + SKILL.md de cada perspectiva).

---

## 📌 Backlog anotado em 2026-04-29

Todos os pendentes deste backlog foram executados. Limpeza CSV, dead code e revisão da geração de arquivos em `13ce2e1`. Verbosidade do log, PRAGMA WAL e documentação dos fingerprints táticos em ciclo seguinte.

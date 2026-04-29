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

## 🔜 Próximas iterações (em ordem de retorno comercial)

### 1. Backend de análise (Stockfish nativo + fila)
**Por quê:** browser-only não escala. Stockfish.js a depth 18 leva horas para 200 partidas; usuário precisa manter aba aberta.
**Como:** Worker Python com `python-chess` + Stockfish nativo, fila Redis ou SQLite-based, endpoint `POST /analyze` que recebe lista de PGNs e devolve direto no DB.
**Impacto:** Destrava produto B2C. Permite análise paralela (4–8 workers), depth 22+, e usuário fecha o app enquanto roda.
**Custo:** 2 dias.

### 2. Meta-prompt versionado para redação automática
**Por quê:** hoje cada `_sections.json` é escrito na mão. Não escala para 100 relatórios/mês.
**Como:** Prompt template em `_chess_shared/redactor_prompt.md` com placeholders para o JSON computado. Chamada via API Anthropic com **prompt caching** (parte estática do prompt cacheia; só o JSON varia). Skill `redactor` invocada por `build.py`.
**Impacto:** Geração end-to-end automática (compute → redação → PDF). Custo por relatório cai pra ~$0.02–0.05.
**Custo:** 1 dia.
**Pré-requisito:** definir voz/tom canônica em forma de exemplos (few-shot).

### 3. Skill `report-coach` (terceira perspectiva)
**Por quê:** B2B (treinador acompanha aluno) é mercado distinto. Coach quer comparar evolução do aluno + comparativo com benchmarks da turma.
**Como:** Reusa `compute.py` + `build.py`; novo template em verde-azulado, foco em delta vs ciclo anterior, comparativos com outros alunos do mesmo treinador.
**Custo:** 1 dia.

### 4. Tabela de telemetria de execução (recalibração da estimativa)
**Por quê:** estimativa de tempo no `index.html` está descalibrada — execuções recentes demoraram bem mais que o estimado.
**Como:** Tabela `execution_logs` no SQLite com `timestamp_start/end`, `duration_seconds`, `depth`, `engine`, `n_failures`, `cache_hit_rate`, `db_hit_rate`, `expected_seconds_at_start`. Após acúmulo de execuções, regressão simples (`actual / expected` médio por engine + depth + n_positions) recalibra `estimateSecondsPerPosition`.
**Custo:** 4h.

### 5. Comparativo cross-jogador
**Por quê:** o SQLite `players` table existe mas não é usado. Querível: "como o `jhoumedeiros` se compara aos outros usuários da minha base?".
**Como:** Nova seção opcional no relatório (myself only): tabela com percentil de score / win-rate / depth de teoria entre os players da DB.
**Custo:** 4h.

### 6. Suporte a Lichess (não só Chess.com)
**Por quê:** muitos jogadores sérios usam Lichess. API é aberta e tem PGN+análise embutida.
**Como:** Adicionar dropdown de "fonte" no `index.html`; novo parser `parseLichessGames`; resto do pipeline reaproveita.
**Custo:** 4h.

### 7. Refactor: separar coleta vs análise no `index.html`
**Por quê:** hoje `index.html` faz coleta + análise. Em coletas grandes o usuário quer rodar a análise depois (ou em outra máquina).
**Como:** Botões separados "Buscar Partidas" → grava `games`, depois "Analisar Stockfish" → consome a tabela. Já parcialmente preparado pelo modo SQLite.
**Custo:** 3h.

### 8. Anti-cheat indireto via score outliers
**Por quê:** o `engine_suspicion_factor` já desconta Score quando ACPL é implausível. Hoje só aplica multiplicativamente; falta seção dedicada.
**Como:** Seção opcional "Sinais de uso de assistência" no relatório (com cuidado linguístico — não acusar, descrever padrão observado: spread por modalidade, ratio acpl/expected por formato).
**Custo:** 4h. Sensibilidade política — pensar antes.

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

### Cobertura de motor
- Manter Stockfish 16 atual ou subir para 17 (já lançado, ~200 Elo a mais)?
- Considerar engine alternativo (Leela Chess Zero) para análise posicional/estratégica diferente.

---

## 🐛 Bugs/débitos técnicos abertos

- **Best_move repetido em CSVs antigos**: corrigido no `index.html` para coletas novas, mas os CSVs históricos têm dados ruins. `build.py` mostra "—" para esses.
- **Coverage de testes**: helpers cobertos, mas pipeline end-to-end (compute → JSON) não tem teste de integração com fixture pequena.
- **Sem CI**: testes rodam só local. Adicionar GitHub Actions com pytest seria o mínimo.
- **Drift entre `theory.md` e SKILL.md**: documentação de redação dispersa em 3 lugares (theory.md compartilhado + SKILL.md de cada perspectiva).

---

## 📌 Backlog anotado em 2026-04-29

Pendências menores remanescentes (limpeza CSV, dead code e revisão da geração de arquivos foram executados em `13ce2e1`).

### Outros itens menores

- Reduzir verbosidade do log do servidor: hoje cada GET /api/* aparece em stderr, polui terminal em sessões longas.
- Adicionar PRAGMA `journal_mode=WAL` em `open_db` para tolerar concorrência futura (compute.py + browser ao mesmo tempo).
- Documentar formato dos fingerprints B/C tático em `theory.md` (hoje só em `build_tactical_index.py` docstring).

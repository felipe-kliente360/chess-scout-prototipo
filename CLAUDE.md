# CLAUDE.md — acordos, padrões e contexto persistente

Documento que preserva decisões combinadas entre Felipe e Claude para o projeto **chess-scout-prototipo**. Carregado automaticamente em toda nova conversa.

Convenção: este arquivo é editável. Quando uma regra aqui ficar obsoleta, **atualize-a** em vez de empilhar contradições.

## Communication Style

Respond terse like smart caveman. Always in pt-BR. All technical substance stay. Only fluff die.
ACTIVE EVERY RESPONSE. No exceptions. No revert.

### Rules

- Drop: articles (a/an/the/o/a/os/as/um/uma), filler (só/basicamente/realmente/simplesmente/literalmente), pleasantries (claro/com certeza/fico feliz em/olá), hedging
- Fragments OK. Short synonyms (grande not extenso, corrigir not "implementar uma solução para")
- Technical terms stay exact
- Code blocks unchanged. Caveman speak around code, not in code
- Error messages quoted exact

### Pattern

[coisa] [ação] [motivo]. [próximo passo].

Not: "Claro! Fico feliz em ajudar com isso. O problema que você está enfrentando provavelmente é causado por..."
Yes: "Bug no middleware de auth. Verificação de expiração usa `<` em vez de `<=`. Fix:"

### Auto-Clarity

Drop caveman only for:

- Avisos de segurança
- Confirmações de ações irreversíveis
- Sequências onde fragmentos causam ambiguidade de risco
  Resume immediately after.

### Boundaries — always normal prose

- Code blocks
- Git commit messages
- PR descriptions

---

## 1. O que é o projeto

Gerador de relatórios analíticos de xadrez (PDF, PT-BR) para jogadores de Chess.com. Pipeline:

```
Coleta (browser, API chess.com)
  → Persistência (SQLite via servidor stdlib)
  → Análise (Stockfish + tema tático + position_facts)
  → Compute (Score blend + agregados)
  → Skill (PT-BR direto, theory.md guia)
  → PDF em data-reports/<user>_<perspective>_<stamp>.pdf
```

Três perspectivas de relatório:

- **`/report-myself <user>`** — "este jogador sou eu" (diagnóstico + plano de estudo)
- **`/report-enemy <user>`** — "este é meu adversário" (plano de combate)
- **`/report-coach <user>`** — "este aluno é meu" (delta vs ciclo anterior + benchmark cross-aluno + plano didático)

Estado completo do produto e roadmap: ver `README.md` e `ROADMAP.md`.

---

## 2. Como Claude deve trabalhar (acordos de processo)

### Commit progressivo, nunca acumular

Após cada feature/refator concluído E validado (smoke test passa), **propor commit imediatamente** antes de seguir para a próxima frente. Não acumular múltiplas features no working tree.

- Mensagem em PT-BR direto, imperativo curto, sem prefixo tipo `feat:`/`fix:` (segue padrão dos commits do repo).
- Quebrar working tree grande em commits temáticos coerentes — não um único "various changes".
- Confirmar antes de commitar (regra de segurança do CLAUDE.md global).
- Se Felipe esquecer de pedir commit no fim de uma feature, lembrar antes de começar a próxima.

**Por que**: já aconteceu de acumular 775 linhas em 4 arquivos modificados sem commit. Histórico fica ilegível, reverter feature isolada vira impossível.

### Push para GitHub só com autorização explícita

`git push origin main` é destrutivo (publica mudanças, atualiza repo público). Confirmar antes. Felipe normalmente aprova; mas a regra é confirmar sempre.

### Auto Mode quando ativo

Quando "Auto Mode Active" aparecer, executar diretamente sem perguntar antes. Felipe escolheu execução autônoma.

Quando inverter (modo direto), perguntar antes de decisões ambíguas. **Operações destrutivas continuam exigindo confirmação mesmo em auto mode** (deletar arquivos, force push, drop database, etc).

### Tom de comunicação

- Direto, sem cerimônia. Sem "vou fazer X", "agora vou Y" — só faça e reporte resultado.
- Quando há decisão ambígua: explica trade-offs e recomenda **uma** opção. Não despeja 4 alternativas pra Felipe escolher.
- Quando o pedido é vago: pergunta com 2-3 opções concretas, não com perguntas abertas.
- **Nunca pomposo ou acadêmico**. Tom direto vale tanto pra resposta no chat quanto pro texto dos relatórios.

### Verificar antes de afirmar

Memórias e contexto antigo podem estar desatualizados. Antes de afirmar "X existe" ou "Y funciona assim", verificar com Read/Grep/Bash. Especialmente para nomes de funções, paths e flags.

---

## 3. Padrões técnicos do projeto

### Pipeline canônico (não suportamos mais o legado)

1. **Pipeline 100% SQLite.** `data/db/history.db` é a fonte única — `games`, `game_analyses`, `analyses`, `players`, `position_cache`. Browser posta no servidor; `compute.py` lê direto.
2. **Servidor local é obrigatório.** Browser via `file://` mostra badge vermelho e bloqueia operações com instrução pra rodar `bash scripts/start.sh` ou `/app-start`.
3. **Output em `data-reports/`** (pasta única, sem subpasta por user). Formato: `<user>_<perspective>_<stamp>.pdf`.
4. **Artefatos de apoio são deletados** após build. `computed.json` e `sections.json` ficam preservados em `analyses.computed_json` no SQLite — qualquer relatório pode ser regerado em ~5s.

### Lifecycle do app

- `bash scripts/start.sh` (ou `/app-start`) — sobe `serve.py` em background, valida `/api/health`, registra PID em `.app-state.json`, abre browser.
- `bash scripts/stop.sh` (ou `/app-stop`) — SIGTERM gracioso, SIGKILL nos sobreviventes, limpa estado.
- Idempotentes nos dois lados.

### Score 0–10 — modelo final (não mexer sem revalidar nos 3 casos extremos)

```
score_10 = 10 × engine_factor × (
  0.5 × ACPL_score      # exp(-(acpl_d20_eq / expected_acpl(rating)) / 2)
+ 0.3 × win_score       # win_rate / 100
+ 0.2 × blunder_score   # 1 / (1 + bpm/5), bpm = blunders por 100 lances (só ≥300cp)
)
```

- `expected_acpl(rating)`: curva chess.com **empírica**, não a teórica antiga. Âncoras: 1000:120, 1400:80, 1800:50, 2200:30, 2500:20.
- `engine_factor`: penalidade quando `ratio = ACPL_d20 / expected < 0.5`. Linear de 1.0 → piso 0.5. Só aplica em ≥100 lances.
- **Canônico (`kpis.score_10`, Opção B)**: `competitive (n≥15)` → `modality_avg (≥2 mods)` → `overall`.
- `score_10_basis` documenta a base eleita.
- 3 casos extremos pra validar: **LucasCamilo10** (farming, deve dar 3.2), **jhoumedeiros** (Daily com motor, deve dar 4.5), **miguelrov** (1424 honesto, deve dar 5.4).

### As 3 camadas de análise (sempre coexistem)

Para todo lance com `loss_cp ≥ 50`:

1. **Stockfish** (sempre, em todo lance)
2. **Tactical theme** (no browser via `tactical-themes.js`, fingerprint do woodpecker)
3. **Position facts** (no Python via `position_facts.py`, 24 detectores; cache delta no DB)

Não há sobreposição — registram juntos. Se o redator quer "stockfish + tema + facts" no mesmo `key_position`, todos os 3 estão lá.

### Camada 4 — análise de tempo (relógio)

Todo lance carrega `clock_ms` (relógio remanescente após o lance, do `[%clk]` no PGN) e `time_spent_ms` (tempo gasto, com increment já aplicado), populados via backfill em `compute.py`. **Não substitui Score** — é contexto narrativo. `compute_time_analysis` produz: tempo por fase, buckets de velocidade da decisão, pressão de relógio (clock <10% do orçamento) com blunder rate dentro/fora, top "pensou e errou" e "errou rápido". Renderiza como Seção 9 dos PDFs. Ignora `time_class='daily'`.

### Paradigmáticas (Seção 7 do PDF)

- **Vitória**: 2 melhores lances do jogador (swing positivo) + 1 pior (loss máx)
- **Derrota**: 2 piores lances do jogador (loss máx) + 1 melhor do adversário (swing contra o jogador)
- Spread mínimo de 8 plies entre os 2 destacados (anti-cascata)
- Ordem cronológica sempre
- Cada `key_position` carrega as 3 camadas

### Estrutura de versionamento

- **Versionado no Git**: `data/openings/eco.json`, `data/openings/*.tsv`, `data/tactical/themes_index.json`. **Bases imutáveis** — fresh-clone funciona sem rebuild.
- **Local apenas (gitignored)**: `data/db/history.db` (+ `-wal`/`-shm`), `data-reports/`, `.app-state.json`, `.app-logs/`, `data/openings/position_cache.json`.

---

## 4. Documentação obrigatória

Nada da skill é opinião do redator. Tudo está ancorado em referências canônicas:

- **`README.md`** — pipeline, arquitetura, conceitos, fluxo. Atualizar quando o produto mudar de comportamento.
- **`ROADMAP.md`** — itens entregues + próximas iterações + decisões em aberto + bugs. Atualizar a cada feature concluída (mover do "Próximas" pra "Entregue").
- **`.claude/skills/_chess_shared/theory.md`** — guia de redação obrigatório. 22 seções cobrindo Score, fases, motivos táticos canônicos, conceitos estratégicos, 7 técnicas posicionais, profilaxia, vieses cognitivos, autores canônicos, position_facts, fingerprints táticos, few-shot examples.
- **`.claude/skills/report-{myself,enemy}/SKILL.md`** — instruções específicas de cada perspectiva (tom, hierarquia das seções, glossas exigidas).
- **`CLAUDE.md`** (este arquivo) — acordos de processo + padrões técnicos.

Quando produto mudar, **atualizar essas docs no mesmo commit** que a mudança de código. README e ROADMAP **não podem** ficar atrás do código.

---

## 5. Decisões tomadas e travadas (não revisitar sem motivo forte)

### Já decididas

| Decisão                                                                       | Data       | Onde detalhar                                               |
| ----------------------------------------------------------------------------- | ---------- | ----------------------------------------------------------- |
| Servidor stdlib (`http.server`), não Flask                                    | 2026-04-29 | Fricção de dep externa não compensa o ganho em UX           |
| SQLite como fonte única, CSV descontinuado                                    | 2026-04-29 | Removido em `13ce2e1`                                       |
| Score blend 50/30/20 + engine_factor + Opção B canônico                       | 2026-04-29 | Validado nos 3 casos extremos. README §"Score"              |
| 3 camadas independentes por posição                                           | 2026-04-29 | Stockfish + tactical + facts; coexistem em `key_position`   |
| Output centralizado em `data-reports/`, sem JSON de apoio                     | 2026-04-29 | Implementado em `13ce2e1`                                   |
| Pasta `data/<user>/` removida (era arquivar; redundante com `analyses` table) | 2026-04-29 | Implementado em `13ce2e1`                                   |
| Lifecycle via `/app-start` e `/app-stop`                                      | 2026-04-29 | Implementado em `397956f`                                   |
| Paradigmáticas no formato 2+1 (não top-3 swing)                               | 2026-04-29 | Validado com LucasCamilo10                                  |
| `data/openings/` e `data/tactical/` versionados, NÃO rebuildar local          | 2026-04-29 | Bases CC0 imutáveis                                         |
| Não vamos fazer exportação DOCX                                               | 2026-04-29 | Removido do roadmap                                         |
| Auto mode é o modo padrão de operação                                         | 2026-04-29 | Felipe confirma direto, não pede planos para tasks pequenas |
| Análise de tempo via `[%clk]` do PGN — não muda Score, vira Seção 9 do PDF    | 2026-04-29 | `clock.py` + backfill em `history.py` + `compute_time_analysis` |
| Skill `assess-data` para resumo da base                                       | 2026-04-29 | Inspeciona history.db, lista users + cobertura das 4 camadas    |
| Skill `report-coach` (3ª perspectiva, B2B)                                    | 2026-04-29 | Voz treinador→aluno; benchmark cross-aluno via `compute_coach_benchmarks` |
| Cache de sections com signature delta                                         | 2026-04-29 | Tabela `sections_cache`; skill consulta via `cache_lookup.py` antes de redigir |
| Telemetria de execução com auto-recalibração                                  | 2026-04-29 | Tabela `execution_logs`; `estimateSecondsPerPosition` usa mediana observada por (engine, depth) |
| Backend Stockfish nativo + fila SQLite                                        | 2026-04-29 | `analyze_worker.py` + `analysis_queue` + endpoints `/api/analyze/{queue,progress}` |
| Redactor automático com prompt caching (~16k tokens cacheados)                | 2026-04-29 | `redactor.py` + `redactor_prompt.md` + flag `--auto-redact` em build.py |
| Anti-cheat via outliers — 4 sinais com semáforo green/yellow/red              | 2026-04-29 | `compute_cheat_signals` em compute.py + macro `cheat_signals_block` |
| Estado persistente do DB no boot + botão "Analisar pendentes sem refetch"     | 2026-04-29 | `refreshDbState` + `analyzePending` em index.html |
| Parâmetros de coleta: sempre por recência, toggle rápida/completa (sem filtro de modalidade) | 2026-05-01 | 30 partidas = direcional; 100 = produção. `QUOTA_MODE` e `TIME_CLASSES` constantes. `fetchProfileTrend` removido. |
| Confiança tática adaptativa: bullet peso 0.4 quando rapid+blitz < 15         | 2026-05-01 | `_MIN_RB_FOR_BULLET_ZERO = 15`; `tactical_confidence` em `kpis.tactical_profile`; SKILL.md das 3 perspectivas atualizados |
| Fila de análise multi-jogador no UI (pausa/stop/resume com ponto salvo)       | 2026-05-01 | `jobQueue`, `runQueuedAnalysis(job)`, painel FILA DE ANÁLISE; `pauseFlag`/`stopFlag`/`resumeFromGame` |

### Em aberto (decidir num próximo ciclo)

- Modelo de produto (B2C jogador casual / B2B treinador / interno) — afeta priorização das próximas iterações
- Modelo de cobrança (se B2C) — por relatório vs assinatura vs freemium. **Custo unitário LLM**: ~R$ 1,08 por relatório sem otimização (Opus 4.7, ~$0.20 a USD/BRL 5,40). Com prompt caching cai pra R$ 0,54; com cache de sections (item #10 do roadmap), R$ 0,11–0,27. Detalhamento + implicações em `ROADMAP.md §Modelo de cobrança`.
- Stockfish 16 vs 17 vs Leela
- Tabela `execution_logs` para recalibrar a estimativa de tempo no `index.html` (item #4 do roadmap)

---

## 6. Comandos rápidos

```bash
# Desenvolvimento
bash scripts/start.sh              # Liga app
bash scripts/stop.sh               # Desliga app
python3.12 -m pytest tests/ -v     # Testes
git status --short                 # Estado do working tree
git log --oneline -10              # Últimos commits

# Pipeline manual (se precisar debugar)
python3.12 .claude/skills/_chess_shared/compute.py <user>
python3.12 .claude/skills/_chess_shared/build.py <user> myself
python3.12 .claude/skills/_chess_shared/build.py <user> enemy

# Slash commands (Claude Code)
/app-start                         # Liga app
/app-stop                          # Desliga app
/assess-data                       # Resumo da base (jogadores, camadas analíticas, depth)
/report-myself <user>              # PDF diagnóstico próprio
/report-enemy <user>               # PDF dossiê de combate
/report-coach <user>               # PDF didático (treinador→aluno: delta + benchmark + plano)
```

```bash
# Cache de sections (regen rápida + economia de tokens)
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/cache_lookup.py <user> <myself|enemy|coach>

# Backend Stockfish nativo (rode em outro terminal)
/opt/homebrew/bin/python3.12 scripts/analyze_worker.py --workers 1 --threads 4 --hash 256
# Flags disponíveis:
#   --movetime1 1000   pass 1 ms (default 1000) — todas as posições
#   --movetime2 2000   pass 2 ms (default 2000) — só suspeitas (~15%)
#   --threads N        threads SF (default cpu_count)
#   --hash MB          hash table SF (default 256; env SF_HASH_MB)
#   --loss-thresh cp   threshold loss_cp para suspeita (default 40)
#   --once             processa fila e sai

# Redactor automático (requer ANTHROPIC_API_KEY)
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/redactor.py <user> <perspective>
# ou direto no build:
/opt/homebrew/bin/python3.12 .claude/skills/_chess_shared/build.py <user> <perspective> --auto-redact
```

---

## 7. Onde Felipe e Claude erraram (lições)

### Acumular features no working tree

- **Aconteceu**: 775 linhas em 4 arquivos sem commit desde `b159c34`. 8 commits temáticos foram criados de uma vez quando o user pediu organizar.
- **Lição**: regra de commit progressivo (seção 2). Sempre que uma feature passa o smoke test, propor commit antes da próxima.

### `expected_acpl` calibrada para torneio clássico

- **Aconteceu**: Score 2.2 pra miguelrov com win 68% — contraintuitivo.
- **Lição**: curva empírica chess.com >> teórica clássica. Validar fórmulas em **3 casos extremos diversos** antes de declarar pronto.

### Score sem âncora em win-rate

- **Aconteceu**: scoring puro de ACPL ignorava resultado das partidas. LucasCamilo10 com 85% win-rate dava Score 0.3.
- **Lição**: blend de múltiplos sinais é mais robusto que métrica única. Win-rate, ACPL e blunders cada um pega aspecto diferente da habilidade.

### Pasta `data/<user>/` virou ruído

- **Aconteceu**: 5 pastas com 9 PDFs antigos + JSONs intermediários acumularam.
- **Lição**: SQLite (`analyses.computed_json`) é fonte canônica suficiente. Salvar artefatos em arquivo é cerimônia inútil quando o DB já guarda tudo.

### `position_features` (lista de tags simples) → `position_facts` (dicts ricos)

- **Aconteceu**: primeira versão era lista plana sem casas, sem métricas. Insuficiente pra narrativa.
- **Lição**: estrutura de dados deve carregar TUDO que o redator pode precisar. Casa específica + métricas auxiliares + status são mais úteis que tags binárias.

---

## 8. Como conversar comigo (Felipe → Claude)

- Pedidos curtos no auto mode → Claude executa direto.
- "explicar X" → resposta didática estruturada com código/dados quando houver.
- "implementar X" → executa, valida, commita (com confirmação se for push).
- "incluir/anotar no roadmap" → só anota em `ROADMAP.md`, não executa.
- "executar item N do roadmap" → executa o que está descrito ali.
- "revisar/reescrever" → audita coerência e atualiza.

Quando algo não está claro ou destoa de uma decisão prévia, eu pergunto antes de agir.

---

## 9. Quando este arquivo precisa ser atualizado

- Após cada decisão arquitetural ou de processo travada (seção 5).
- Quando uma regra de processo da seção 2 mudar.
- Quando uma decisão da seção 5 for revisada (atualizar a linha, não criar nova).
- Quando um padrão técnico da seção 3 mudar.
- Quando emergir uma lição da seção 7 que valha registrar.

Última atualização: 2026-05-01 — Simplificação params coleta (rápida/completa por recência); confiança tática adaptativa (bullet fallback, `tactical_confidence`); fila de análise multi-jogador (pausa/stop/resume).

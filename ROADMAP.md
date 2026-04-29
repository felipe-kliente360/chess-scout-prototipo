# Roadmap — chess-scout-prototipo

Histórico das decisões de design + próximos passos pendentes. Vivente: atualizar a cada ciclo de evolução.

---

## ✅ Entregue (até 2026-04-29)

### Coleta e análise
- Coleta via Chess.com API direto no browser, com filtros de ritmo (bullet/blitz/rapid/daily) e contagem mínima de plies (≥15).
- Stockfish.js depth 18 com handshake `isready/readyok` (eliminou bug de `best_move` repetido entre plies).
- Validação UCI: `best_move` retornado pelo motor é checado contra a posição via `chess.js`; se ilegal, vira string vazia.
- Classificação de aberturas via base ECO do Lichess (3.690 posições EPD-indexadas).
- **Cache de posições SQLite** (`history.db`): hit-rate alto em re-coletas; backfill via `scripts/build_position_cache.py`.

### Análise (compute.py)
- **Score 0–10 calibrado** por depth + rating do jogador (`expected_acpl(rating) * depth_factor(depth)`). Baseline 6 = "jogou como esperado para o rating".
- **Filtro de relevância** aplicado ao universo analítico: ≥25 lances, sem `abandoned`/early `timeout`/`resigned`. Win-rate continua sobre universo completo.
- **Confiabilidade da amostra** = ponderada por amostra (50%) + depth (30%) + cobertura ECO (20%).
- **Programa de puzzles** auto-derivado do perfil + faixa de rating (consumível por app externo).
- **Persistência longitudinal**: `players` + `analyses` no SQLite. Histórico carregado no build para gerar tabela + sparkline de evolução.

### Relatórios (build.py + templates)
- Duas perspectivas: `/report-myself` (verde, plano de estudo) e `/report-enemy` (vermelho, plano de combate).
- Templates compartilham `_chess_shared/base.css` + `_chess_shared/macros.html` (drift impossível para componentes comuns).
- Seção 7 com lances **decisivos** (eval swing, não loss_cp do usuário) + setas (vermelho jogado, verde melhor) + tabuleiro orientado pela cor do jogador analisado.
- Notação SAN limpa em vez de UCI (`Bcd7` em vez de `c7d7`).
- Legenda de score na capa, header com confiabilidade %, mensagens de filtro em linguagem natural.

### Qualidade
- 55 testes pytest passando (helpers de score, expected_acpl, depth_factor, classify_loss, phase_of_ply, history, position_cache).

---

## 🔜 Próximas iterações (em ordem de retorno comercial)

### 1. Backend de análise (Stockfish nativo + fila)
**Por quê:** browser-only não escala. Stockfish.js a depth 18 leva horas para 200 partidas; usuário precisa manter aba aberta.
**Como:** Worker Python com `python-chess` + Stockfish nativo, fila Redis ou SQLite-based, endpoint `POST /analyze` que recebe lista de PGNs e devolve CSV pronto.
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
**Como:** Reusa `compute.py` + `build.py`; novo template em verde-azulado, foco em delta vs ciclo anterior, comparativos com outros alunos do mesmo treinador, exportação editável.
**Custo:** 1 dia (já que arquitetura suporta).

### 4. Score por `time_class` movido para fórmula
**Por quê:** hoje mostramos `by_time_class` separado, mas o score geral mistura tudo (Daily inflando o número). Score deveria ponderar pela mistura.
**Como:** No JSON, expor `score_10_rapid_only`, `score_10_daily_only` etc. e usar o `rapid` como score "principal" do header quando houver volume suficiente.
**Custo:** 3h.

### 5. Comparativo cross-jogador
**Por quê:** o SQLite `players` table existe mas não é usado. Querível: "como o `jhoumedeiros` se compara aos outros usuários da minha base?".
**Como:** Nova seção opcional no relatório (myself only): tabela com percentil de score / win-rate / depth de teoria entre os players da DB.
**Custo:** 4h.

### 6. Suporte a Lichess (não só Chess.com)
**Por quê:** muitos jogadores sérios usam Lichess. API é aberta e tem PGN+análise embutida (lichess.org/api/games/user/`<user>`).
**Como:** Adicionar dropdown de "fonte" no `index.html`; novo parser `parseLichessGames`; resto do pipeline reaproveita.
**Custo:** 4h.

### 7. PWA + IndexedDB (cache no browser sem backend)
**Por quê:** cache de posições hoje exige rodar `export_cache.py` antes da coleta. Se o browser cachear sozinho via IndexedDB, fica auto.
**Como:** Service worker que mantém `position_cache` em IndexedDB; sync periódico com SQLite via download/upload manual.
**Custo:** 1 dia.

### 8. Refactor: separar coleta vs análise no `index.html`
**Por quê:** hoje `index.html` faz coleta + análise. Em coletas grandes o usuário quer rodar a análise depois (ou em outra máquina).
**Como:** Botões separados "Baixar PGNs" → CSV intermediário, depois "Carregar CSV → Analisar". Permite quebrar o fluxo.
**Custo:** 3h.

### 9. Anti-cheat indireto via score outliers
**Por quê:** o `score_calibration.performance_ratio` já detecta jogadores que jogam muito acima do rating (ratio < 0.15 sustentado). Hoje só aparece como warning.
**Como:** Seção opcional "Sinais de uso de assistência" no relatório (com cuidado linguístico — não acusar, descrever padrão observado).
**Custo:** 4h. Sensibilidade política — pensar antes.

### 10. Exportação editável (DOCX além de PDF)
**Por quê:** treinadores querem editar o texto antes de mandar pro aluno.
**Como:** Adicionar export DOCX usando `python-docx`. Mesmo conteúdo, formato editável.
**Custo:** 6h.

---

## ❓ Decisões estratégicas em aberto

### Modelo de produto
- **B2C** (jogador casual): prioridade 1 + 2 (backend + redação automática). Sem isso, custo unitário inviável.
- **B2B** (treinador/clube): prioridade 3 + 5 + 10 (perspectiva coach + comparativo + DOCX).
- **Interno/amigos**: MVP atual já entrega; investir em 4 (qualidade do score) e 6 (Lichess).

### Modelo de cobrança (se B2C)
- Por relatório (R$ X cada).
- Assinatura mensal (1 relatório/mês incluído + cache acumulado).
- Freemium: 1 relatório grátis com sample reduzido, paga full.

### Cobertura de motor
- Manter Stockfish 16 atual ou subir para 17 (já lançado, ~200 Elo a mais)?
- Considerar engine alternativo (Leela Chess Zero) para análise posicional/estratégica diferente.

---

## 🐛 Bugs/débitos técnicos abertos

- **Best_move repetido em CSVs antigos**: corrigido no `index.html` para coletas novas, mas os CSVs históricos têm dados ruins. `build.py` mostra "—" para esses. Não dá para retroativamente corrigir sem re-analisar.
- **Coverage de testes**: helpers cobertos, mas pipeline end-to-end (compute → JSON) não tem teste de integração com fixture CSV pequeno.
- **Sem CI**: testes rodam só local. Adicionar GitHub Actions com pytest seria o mínimo.
- **Drift entre `theory.md` e SKILL.md**: documentação de redação dispersa em 3 lugares (theory.md compartilhado + SKILL.md de cada perspectiva). Considerar consolidar.

---

## 📌 Backlog anotado em 2026-04-29

Itens identificados durante o ciclo de melhorias mas não executados. Trazer próximo ciclo.

### Recalibração do Score 0–10 (alta prioridade)

Inconsistência identificada com miguelrov: rating 1424, win-rate 68%, ACPL 80, mas Score atual 2.2. A fórmula `expected_acpl(rating) = 130 * exp(-rating/1200)` foi calibrada para torneio clássico — gera expectativa irrealista para chess.com online onde 1400 joga ACPL ~80 normalmente. Três caminhos discutidos:

- **Caminho A (cirúrgico)**: recalibrar `expected_acpl` para curva chess.com empírica (1000:120, 1400:80, 1800:50, 2200:30, 2500:20). Score atual 2.2 viraria ~5.5–6.0 sem mudar mais nada.
- **Caminho B (estrutural)**: introduzir `score_10_blend` como variante combinando 50% win-rate normalizado + 30% ACPL relativo + 20% redução de blunders. Mais coerente com as outras métricas, requer normalização de "expected win rate" pelo rating médio dos adversários.
- **Caminho C (radical)**: eliminar Score, usar Accuracy% direta. Mais transparente, perde o "calibrado por rating".

Decisão pendente: A primeiro com curva publicada (Lichess/chess.com), depois B se ainda houver incoerência. Validar nos 3 casos extremos: LucasCamilo10 (1824 com farming), miguelrov (1424 honesto), jhoumedeiros (Daily com motor).

### Limpeza do método CSV legado

Pipeline CSV existe hoje só como fallback quando `history.db` está vazio para o user. Considerar remoção completa:

- Apagar funções `find_latest_csvs`, `load_from_db` deixa de ser flag e vira default
- Remover `scripts/import_csv_to_db.py` após validar que não há mais CSVs históricos a importar
- Remover modo `FILE MODE` do `index.html` (badge cinza, fluxo de download de CSV)
- Skills `report-myself` / `report-enemy` deixam de mencionar fallback CSV
- README perde a seção "Modo legado (CSV)"

Trade-off: simplifica codebase em ~200 linhas mas obriga rodar servidor local sempre. Aceitável dado que servidor é stdlib (zero deps externas).

### Limpeza de históricos e dead code

- `data/<user>/*_report/` arquivados: revisar se há PDFs antigos com modelos/scores desatualizados que poluem comparação longitudinal
- `position_cache.json` exportado para o browser: confirmar se ainda é usado dado que `game_analyses` no DB cobre o mesmo papel via API
- `scripts/`: 6+ scripts legados (build_position_cache, export_cache, enrich_eco, filter_short_games, import_new_analysis) — auditoria de quais ainda fazem sentido
- `compute.py`: depois da refatoração para `--from-db` e remoção do fallback CSV, várias funções (`find_latest_csvs`, `load_previous_computed` parcial) ficam mortas
- Variáveis e helpers de score que não são mais canônicos pós-refator (depende de qual caminho da recalibração for adotado)

### Revisão das funções de geração de arquivos finais

Auditar o que `build.py` e `compute.py` produzem ao final de uma execução:

- `compute.py` salva `data/<user>_<stamp>_computed.json` em `data/` raiz, depois `build.py` move para `data/<user>/<stamp>_<perspective>_report/`. Confirmar que essa cerimônia ainda faz sentido vs salvar direto na pasta final.
- `analyses` table no SQLite armazena `computed_json` completo como TEXT — pode duplicar com o arquivo. Decidir fonte canônica.
- Snapshots PDF: política de retenção. Hoje todos ficam, sem limite. Considerar limpeza automática de snapshots antigos do mesmo user (manter os últimos N).
- Sections JSON: similar, todos ficam. Útil para reprocessar com template novo, mas cresce sem bound.

### Outros itens menores

- Reduzir verbosidade do log do servidor: hoje cada GET /api/* aparece em stderr, polui terminal em sessões longas.
- Adicionar PRAGMA `journal_mode=WAL` em `open_db` para tolerar concorrência futura (compute.py + browser ao mesmo tempo).
- Documentar formato dos fingerprints B/C tático em `theory.md` (hoje só em `build_tactical_index.py` docstring).

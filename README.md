# chess-scout

Transforma suas partidas do Chess.com em um relatório de análise em PDF, em português, com diagnóstico real e plano de ação concreto.

---

## O que é

**chess-scout** analisa suas partidas recentes e responde três perguntas que plataformas como Chess.com e Lichess não respondem bem:

- **O que devo estudar nos próximos 30 dias para melhorar de verdade?**
- **Como me preparar para enfrentar este adversário específico?**
- **Em quais situações eu vejo o tabuleiro melhor — e em quais eu falho?**

O resultado é um PDF em português, direto, sem jargão técnico, com números reais das suas partidas e um plano de estudo baseado neles.

---

## Dois tipos de relatório

### 📘 Relatório "Eu" — diagnóstico próprio

Para quando você quer melhorar seu próprio jogo. O relatório responde:

- Em qual fase (abertura, meio-jogo, finais) você perde mais pontos?
- Quais padrões táticos você não enxerga quando estão disponíveis?
- Quais aberturas te servem — e quais você deveria trocar?
- Como você usa o relógio e quando ele te prejudica?
- O que estudar primeiro com base no maior retorno por hora investida?

### 🎯 Relatório "Adversário" — dossiê de combate

Para quando você vai enfrentar alguém específico e quer se preparar. O relatório responde:

- O que ele joga mais — e o que induzi-lo a jogar onde ele perde?
- Onde ele é sólido (evitar) e onde ele desmorona (atacar)?
- Em quais padrões táticos ele cai com mais frequência?
- Como ele usa o tempo e quando ele colapsa sob pressão?
- Quais armadilhas e sequências você pode preparar contra ele?

---

## Três níveis de análise

A profundidade do relatório depende do modo que você escolher no app:

| | Flash | Rápida | Completa |
|---|---|---|---|
| Partidas coletadas | 200 | 30 | 100 |
| Análise de lances | Não | Seus lances | Todos os lances |
| Erros táticos detectados | Não | Seus (tipo A) | Todos (A + B + C) |
| Padrões posicionais | Não | Parcial | Completo |
| Gestão de tempo | Sim | Sim | Sim |
| Aberturas | Sim | Sim | Sim |
| Tempo aproximado | ~1 min | ~5 min | ~30 min |

**Flash** — Visão rápida de repertório e volume. Sem análise individual de lances. Útil para primeira impressão ou quando o tempo é curto.

**Rápida** — Analisa seus lances principais. Detecta os padrões táticos que você deixou passar. Bom para diagnóstico direcional sem esperar meia hora.

**Completa** — Analisa todos os lances dos dois lados. Detecta também quando seus erros criaram oportunidades para o adversário e quando ele te perdoou. Base para o relatório mais completo.

---

## O que o app analisa em cada lance

Para cada lance relevante, três perguntas independentes:

**1. Qualidade do lance**
Qual era o melhor lance possível? Quanto você perdeu ao jogar diferente? A diferença acumulada ao longo da partida compõe seu score 0–10.

**2. Havia uma tática disponível?**
Garfo, cravada, espeto, mate, sacrifício... O app cruza a posição com uma base de 308 mil puzzles para detectar se havia um motivo tático disponível e se você o jogou ou não.

**3. Como estava o tabuleiro estruturalmente?**
Rei exposto? Peão isolado? Escudo quebrado? Coluna aberta perto do rei? 24 detectores automáticos mapeiam o contexto posicional de cada erro — o que ajuda a entender *por que* você errou, não só *onde*.

---

## Os três tipos de erro tático

Quando há uma tática disponível numa posição:

- **Tipo A** — Você tinha a tática no seu lance mas não jogou. O erro é seu — cegueira tática.
- **Tipo B** — Seu lance criou uma tática para o adversário, e ele aproveitou. O erro é posicional.
- **Tipo C** — Seu lance criou uma tática para o adversário, mas ele não viu. Você teve sorte.

O modo **Rápida** detecta só tipo A (seus erros diretos). O modo **Completo** detecta A, B e C.

---

## O que está em cada seção do relatório

Todos os relatórios abrem com um **painel de dados** — todas as tabelas, gráficos e métricas juntos — para você ter o contexto completo antes de ler a análise narrativa.

Depois, o relatório segue o fluxo natural de uma partida:

| Seção | O que você vai ler |
|---|---|
| **Situação geral** | Onde você está hoje em score, win-rate e confiabilidade da amostra |
| **Abertura e desenvolvimento** | O que você joga, com que profundidade de teoria, onde improvisa cedo |
| **Meio-jogo — táticas e estratégia** | Padrões táticos que você erra + estruturas posicionais que dominam seus erros, integrados |
| **Como conduz finais** | Onde você ganha ou perde pontos na fase final |
| **Padrões por cor** | Você é diferente com brancas vs pretas? Por quê? |
| **Gestão de tempo** | Quando o relógio te prejudica e em quais situações você decide rápido demais |
| **Partidas relevantes** | 4 partidas reais que provam o diagnóstico — 2 vitórias + 2 derrotas |
| **Pontos fortes e fracos** | Síntese do diagnóstico completo |
| **Como adversários te vencem** | A perspectiva de quem está do outro lado |
| **Plano de estudo** | 3–5 coisas para estudar nos próximos 30 dias, por retorno |

No relatório do adversário, as seções de análise descrevem o jogo *dele*, e o bloco final vira plano de combate: o que evitar, como atacar, armadilhas a induzir.

---

## Score 0–10

Em vez de "Accuracy 94%" — um número que não diz o que fazer — o chess-scout calcula um score composto:

- **50%** precisão dos lances, calibrada pelo seu rating (um 1200 que joga como 1200 tira 5.0, não 2.0)
- **30%** resultado das partidas (win-rate)
- **20%** frequência de erros graves

O score é calculado só nas partidas competitivas (adversários próximos do seu rating), o que elimina o viés de partidas fáceis ou difíceis demais.

---

## Como usar

### Pré-requisitos

```bash
brew install python@3.12 pango
python3.12 -m pip install --break-system-packages pandas jinja2 chess weasyprint
```

### Primeira vez — clone e pronto

Não precisa rodar nenhum build. As bases de aberturas e táticas já vêm no repositório.

```bash
git clone <repo>
cd chess-scout-prototipo
```

### Fluxo de uso

```bash
# 1. Liga o app
bash scripts/start.sh

# 2. Abre http://127.0.0.1:8000/ no navegador
#    → digita o username do Chess.com
#    → escolhe o modo (Flash / Rápida / Completa)
#    → clica "Buscar Partidas" → "Analisar"

# 3. Gera o PDF (via Claude Code)
/report-myself <username>    # relatório de diagnóstico próprio
/report-enemy <username>     # dossiê de combate

# 4. Desliga
bash scripts/stop.sh
```

O PDF fica em `data-reports/<username>_<perspectiva>_<data>.pdf`.

### Comandos disponíveis

| Comando | Função |
|---|---|
| `/app-start` | Liga o servidor local |
| `/app-stop` | Desliga |
| `/report-myself <user>` | PDF de diagnóstico próprio + plano de estudo |
| `/report-enemy <user>` | PDF de dossiê de combate |
| `/report-coach <user>` | PDF didático para treinadores (delta + benchmark + plano de 4 semanas) |
| `/assess-data` | Resumo do que está no banco de dados |

---

## Dados — o que fica salvo e onde

Tudo fica em `data/db/history.db` — um arquivo SQLite local, só na sua máquina, nunca sobe para o repositório.

- **Partidas**: deduplicadas por URL. Recoleta nunca duplica.
- **Análises**: organizadas por partida + lance + profundidade. Re-analisar com mesma profundidade é instantâneo (reusa o que já está salvo).
- **Snapshots**: cada relatório gerado salva um snapshot completo dos dados — você pode re-gerar o PDF em ~5s sem refazer a análise.

O que é gitignored (dados locais, não sobem):
- `data/db/history.db` — partidas e análises
- `data-reports/` — PDFs gerados
- `.app-state.json` e `.app-logs/` — estado do servidor

---

## Arquitetura (para quem quiser entender o pipeline)

```
Browser (http://127.0.0.1:8000/)
  Coleta partidas via chess.com API
  Analisa cada lance: Stockfish WASM + tema tático + fatos estruturais
  POST → serve.py (servidor Python local, stdlib)
         ↓
  data/db/history.db (SQLite)
         ↓
  compute.py → score, agregados, paradigmáticas, position_facts
         ↓
  Claude (skill) → redige seções em PT-BR
         ↓
  build.py (Jinja2 + WeasyPrint) → PDF
```

**Stack**:
- Frontend: HTML/JS vanilla, `chess.js`, `stockfish.js` (WASM)
- Backend: Python 3.12, `pandas`, `python-chess`, `jinja2`, `weasyprint`
- Servidor: stdlib `http.server` (sem Flask, sem dependências extras)
- Persistência: SQLite local

---

## Próximos passos

Ver [`ROADMAP.md`](ROADMAP.md).

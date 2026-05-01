# Implementação: Análise Tática para Woodpecker App

## Contexto

Este projeto é o Woodpecker App, app de treino tático de xadrez hospedado no Netlify (frontend estático). Vamos adicionar uma feature: dado um username do Chess.com, analisar as últimas 30 partidas e gerar um conjunto personalizado de temas táticos para treino.

Existe um repositório irmão chamado `chess-scout-prototipo` (github.com/felipe-kliente360/chess-scout-prototipo) que já tem toda a lógica de análise construída e validada. Dois arquivos desse repo precisam ser copiados para cá — instruções abaixo.

---

## Decisão de arquitetura

100% browser-side. Sem servidor. Sem backend Python. Sem API nova.

O pipeline completo roda no cliente:
1. Fetch das partidas via Chess.com API (CORS aberto)
2. Análise Stockfish via stockfish.js WASM (já roda no browser)
3. Classificação de temas táticos via `tactical-themes.js` (já é browser-native)
4. Agregação e geração do `puzzle_program` em JS (port da lógica Python — código completo abaixo)

Netlify serve os arquivos estáticos. Resultado armazenado em IndexedDB para cache entre sessões.

---

## Input / Output da feature

**Input (UI):**
- Username Chess.com (campo texto)
- Modo fixo: rápida (30 partidas mais recentes, todos os formatos)

**Output (`puzzle_program`):**
```json
{
  "username": "miguelrov",
  "suggested_rating": 1200,
  "rating_range": [1100, 1300],
  "tactical_confidence": {
    "level": "alta",
    "n_rapid_blitz": 22,
    "weights_adapted": false,
    "note": ""
  },
  "themes": [
    { "theme": "fork",        "priority": "alta",  "source": "detected", "label": "garfo — uma peça ataca duas ao mesmo tempo" },
    { "theme": "pin",         "priority": "alta",  "source": "detected", "label": "cravada — peça presa que não pode mover sem expor outra" },
    { "theme": "backRankMate","priority": "média",  "source": "rating",   "label": "mate na fila do fundo" }
  ]
}
```

Os nomes de `theme` são camelCase Lichess exato — compatíveis diretamente com o Woodpecker para montar conjuntos de treino.

---

## Passo 1 — Copiar arquivos do chess-scout-prototipo

### 1a. `tactical-themes.js` → copiar verbatim

Buscar via raw GitHub:
```
https://raw.githubusercontent.com/felipe-kliente360/chess-scout-prototipo/main/tactical-themes.js
```

Salvar como `src/chess/tactical-themes.js` (ou path equivalente no projeto).

**Não modificar o arquivo.** Depende de `chess.js@0.10.3` — verificar se já existe no projeto; se não, adicionar.

Ajustar a constante `TACTICAL_INDEX_URL` no topo do arquivo para o path correto do `themes_index.json` no Woodpecker (default é `data/tactical/themes_index.json`).

API pública exposta pelo arquivo:
```js
TacticalThemes.loadTacticalIndex()
// carrega o índice JSON lazy (uma única vez, cacheado)

TacticalThemes.classifyPosition(fen, bestUci, playedUci)
// → { theme, confidence, source, themes: [{theme, confidence}], fingerprint }
// → null se sem match
```

### 1b. `data/tactical/themes_index.json` → adicionar como asset estático

Buscar via raw GitHub (arquivo de 4MB / ~440KB gzip):
```
https://raw.githubusercontent.com/felipe-kliente360/chess-scout-prototipo/main/data/tactical/themes_index.json
```

Hospedar em `/public/data/tactical/themes_index.json` (ou path equivalente). É uma base CC0 de fingerprints táticos derivada de 308k puzzles do Lichess — não precisa ser gerada, só copiada.

---

## Passo 2 — Implementar `src/chess/tactical-aggregator.js`

Port da lógica Python do `chess-scout-prototipo`. Implementar as seguintes constantes e funções:

```js
// ── Constantes ────────────────────────────────────────────────────────────

const TC_WEIGHTS = { rapid: 2.0, blitz: 1.0, bullet: 0.0, daily: 0.0 };
const ROLE_WEIGHTS = { A: 1.5, B: 1.2, C: 0.6 };
const RANK_FACTOR  = [1.0, 0.5, 0.25]; // top-1, top-2, top-3 temas por posição
const MIN_RB_FOR_BULLET_ZERO = 15;      // se rapid+blitz < 15, bullet vira 0.4

const CANONICAL_THEMES = {
  fork:               "garfo — uma peça ataca duas ao mesmo tempo",
  pin:                "cravada — peça presa que não pode mover sem expor outra",
  skewer:             "espeto — força a peça da frente a sair, capturando a de trás",
  discoveredAttack:   "ataque descoberto — uma peça sai e revela ataque de outra",
  doubleCheck:        "xeque duplo — duas peças dão xeque, rei obrigado a mover",
  deflection:         "desvio — força peça defensora a sair de função",
  attraction:         "atração — atrai peça para casa ruim (isca)",
  capturingDefender:  "remoção do defensor — captura ou afasta quem protege",
  backRankMate:       "mate na fila do fundo — rei sem fuga na 1ª/8ª linha",
  smotheredMate:      "mate sufocado — cavalo dá mate com peças próprias bloqueando",
  sacrifice:          "sacrifício — entregar material por vantagem maior",
  intermezzo:         "lance intermediário (intermezzo) — forçante antes do esperado",
  kingsideAttack:     "ataque ao rei — sacrifícios em h7/g7, abrir colunas",
  attackingF2F7:      "ataque em f2/f7 — armadilha de abertura em casa fraca",
  rookEndgame:        "final de torres — Lucena, Philidor, atividade da torre",
  pawnEndgame:        "final de peões — oposição, regra do quadrado",
  mateIn1:            "mate em 1",
  mateIn2:            "mate em 2 — sequência forçada",
  overloading:        "sobrecarga — peça defensora com tarefas demais",
  trappedPiece:       "peça presa — sem escapatória sem perda material",
  xRayAttack:         "raio X — ataque que atravessa peça intermediária",
  capturingDefender:  "remoção do defensor",
  queensideAttack:    "ataque na ala da dama",
  promotion:          "promoção — peão chega à 8ª fileira",
  enPassant:          "en passant",
};

// ── aggregateTactical ─────────────────────────────────────────────────────
//
// moves: array de objetos com campos:
//   game_index       number
//   time_class       'rapid'|'blitz'|'bullet'|'daily'
//   loss_cp          number (>=0)
//   tactical_theme   string|null
//   tactical_confidence  number|null
//   tactical_themes  array [{theme, confidence}]|null  (top-3 por posição)
//   tactical_role    'A'|'B'|'C'|null
//
// Retorna { weighted_top, role_totals, tactical_confidence }

export function aggregateTactical(moves) {
  // Conta jogos por time_class para decidir peso adaptativo do bullet
  const gameTimeClasses = {};
  for (const m of moves) gameTimeClasses[m.game_index] = m.time_class;

  const tcCounts = {};
  for (const tc of Object.values(gameTimeClasses))
    tcCounts[tc] = (tcCounts[tc] || 0) + 1;

  const nRapidBlitz = (tcCounts.rapid || 0) + (tcCounts.blitz || 0);
  const nBullet     = tcCounts.bullet || 0;
  const bulletW     = nRapidBlitz >= MIN_RB_FOR_BULLET_ZERO ? 0.0
                    : nBullet > 0 ? 0.4 : 0.0;
  const weightsAdapted    = bulletW > 0;
  const effectiveWeights  = { ...TC_WEIGHTS, bullet: bulletW };

  const weighted    = {};
  const breakdown   = {}; // theme → {A, B, C}
  const roleTotals  = { A: 0, B: 0, C: 0 };

  const flagged = moves.filter(m =>
    m.tactical_role &&
    m.tactical_theme &&
    (m.loss_cp || 0) >= 50
  );

  for (const m of flagged) {
    const role  = m.tactical_role || 'B';
    const tc    = m.time_class    || 'blitz';
    const tcW   = effectiveWeights[tc] ?? 0;
    if (tcW === 0) continue;

    const roleW = ROLE_WEIGHTS[role] || 1.0;

    // Constrói lista de (theme, rankFactor) a partir de tactical_themes (top-3)
    // ou cai de volta para tactical_theme (top-1)
    let themeEntries = [];
    if (Array.isArray(m.tactical_themes) && m.tactical_themes.length) {
      themeEntries = m.tactical_themes.slice(0, 3).map((t, i) => ({
        theme: typeof t === 'string' ? t : t.theme,
        rf: RANK_FACTOR[i] ?? 0.25,
      }));
    } else if (m.tactical_theme) {
      themeEntries = [{ theme: m.tactical_theme, rf: 1.0 }];
    }

    for (const { theme, rf } of themeEntries) {
      if (!theme) continue;
      const w = roleW * tcW * rf;
      weighted[theme]  = (weighted[theme]  || 0) + w;
      if (!breakdown[theme]) breakdown[theme] = { A: 0, B: 0, C: 0 };
      breakdown[theme][role] += w;
      roleTotals[role] = (roleTotals[role] || 0) + w;
    }
  }

  const top5 = Object.entries(weighted)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([theme, score]) => ({
      theme,
      score:     Math.round(score * 100) / 100,
      breakdown: breakdown[theme],
    }));

  // Nível de confiança da amostra tática
  const totalWeighted = Object.values(weighted).reduce((a, b) => a + b, 0);
  let level, note;
  if (nRapidBlitz >= 15 && totalWeighted > 0) {
    level = 'alta';        note = '';
  } else if (nRapidBlitz >= 8) {
    level = 'média';       note = `${nRapidBlitz} partidas rapid/blitz — ranking pode variar com mais dados.`;
  } else if (totalWeighted > 0) {
    level = 'baixa';
    note  = weightsAdapted
      ? `Apenas ${nRapidBlitz} rapid/blitz — bullet incluído com peso reduzido (0.4). Resultado indicativo.`
      : 'Amostra dominada por daily — análise tática limitada.';
  } else {
    level = 'insuficiente'; note = 'Sem partidas rapid/blitz/bullet analisáveis.';
  }

  return {
    weighted_top:        top5,
    role_totals:         roleTotals,
    tactical_confidence: { level, n_rapid_blitz: nRapidBlitz, weights_adapted: weightsAdapted, note },
  };
}

// ── derivePuzzleProgram ───────────────────────────────────────────────────
//
// tacticalProfile : saída de aggregateTactical()
// avgRating       : número — média de rating do jogador nas partidas analisadas
// errorsByPhase   : { opening: N, middlegame: N, endgame: N } — opcional

export function derivePuzzleProgram(tacticalProfile, avgRating, errorsByPhase = {}) {
  const rating = avgRating || 1200;
  const seen   = new Set();
  const themes = [];

  // 1. Fraquezas detectadas nas partidas (fonte mais confiável)
  for (const entry of (tacticalProfile.weighted_top || []).slice(0, 4)) {
    if (!entry.theme || seen.has(entry.theme)) continue;
    const roleA    = entry.breakdown?.A || 0;
    const priority = roleA >= entry.score * 0.5 ? 'alta' : 'média';
    themes.push({
      theme:    entry.theme,
      priority,
      source:   'detected',
      label:    CANONICAL_THEMES[entry.theme] || entry.theme,
    });
    seen.add(entry.theme);
  }

  // 2. Heurísticas por fase (complementam se detecção insuficiente)
  const total   = Math.max(1,
    (errorsByPhase.opening    || 0) +
    (errorsByPhase.middlegame || 0) +
    (errorsByPhase.endgame    || 0));
  if ((errorsByPhase.endgame || 0) / total >= 0.4) {
    for (const t of ['rookEndgame', 'pawnEndgame']) {
      if (!seen.has(t)) {
        themes.push({ theme: t, priority: 'alta', source: 'heuristic', label: CANONICAL_THEMES[t] || t });
        seen.add(t);
      }
    }
  }
  if ((errorsByPhase.middlegame || 0) / total >= 0.4 && !seen.has('fork')) {
    themes.push({ theme: 'fork', priority: 'alta', source: 'heuristic', label: CANONICAL_THEMES.fork });
    seen.add('fork');
  }

  // 3. Fundamentos por faixa de rating
  const byRating =
    rating < 1000 ? [['fork','alta'],['pin','alta'],['backRankMate','média']] :
    rating < 1400 ? [['discoveredAttack','alta'],['deflection','média'],['backRankMate','média']] :
    rating < 1800 ? [['capturingDefender','alta'],['skewer','média'],['kingsideAttack','média']] :
                    [['intermezzo','alta'],['overloading','média'],['sacrifice','média']];

  for (const [t, pr] of byRating) {
    if (!seen.has(t)) {
      themes.push({ theme: t, priority: pr, source: 'rating', label: CANONICAL_THEMES[t] || t });
      seen.add(t);
    }
  }

  return {
    suggested_rating:    rating,
    rating_range:        [Math.max(400, rating - 100), Math.min(2800, rating + 100)],
    tactical_confidence: tacticalProfile.tactical_confidence,
    themes:              themes.slice(0, 8),
  };
}
```

---

## Passo 3 — Implementar `src/chess/chess-analysis.js`

Orquestrador principal. Exportar a função `analyzePlayer(username, onProgress)`.

**Parâmetros fixos (não expor na UI):**
```js
const GAMES_TARGET    = 30;   // modo rápida fixo
const MOVETIME_MS     = 200;  // suficiente para classificação tática; não usar 1000ms
const MIN_PLIES       = 15;   // ignorar partidas muito curtas
const LOSS_THRESHOLD  = 50;   // loss_cp mínimo para marcar posição como erro
```

**Fluxo completo:**

```
1. fetchGames(username, 30)
   - Chess.com API: GET https://api.chess.com/pub/player/{username}/games/{YYYY}/{MM}
   - Iterar meses do mais recente ao antigo
   - Parar ao acumular 30 partidas com n_plies >= MIN_PLIES
   - Retornar array de { pgn, time_class, my_rating, color, result, opponent_rating }

2. Verificar cobertura tática:
   - Contar rapid+blitz; logar warning se < 15
   - Se zero rapid/blitz/bullet: retornar erro "amostra insuficiente"

3. Para cada partida (com onProgress callback):
   a. extractMoves(pgn)
      → array de { fen_before, move_uci, move_san, ply, side_to_move }

   b. Para cada lance:
      i.  analyzePosition(fen_before) via stockfish.js
          → { best_move, evaluation, cp }
          → usar limit: { time: MOVETIME_MS / 1000 }
      ii. TacticalThemes.classifyPosition(fen_before, best_move, move_uci)
          → { theme, confidence, themes (top-3 array) } ou null

   c. Calcular loss_cp para cada lance:
      loss_cp[i] = max(0, cp[i] + cp[i+1])
      (cp[i+1] é do lado adversário — soma porque perspectiva invertida)

   d. Atribuir tactical_role:
      - Lance do JOGADOR com loss_cp >= 50 e best_move tinha tema → role = 'A'
      - Lance do JOGADOR com loss_cp >= 100: buscar tema no lance seguinte do adversário
        → se adversário explorou (loss_opp < 100): role = 'B'
        → se adversário não explorou: role = 'C'

4. aggregateTactical(todosOsLances) → tactical_profile
   (importar de tactical-aggregator.js)

5. avgRating = média de my_rating nas partidas coletadas

6. derivePuzzleProgram(tactical_profile, avgRating) → puzzle_program
   (importar de tactical-aggregator.js)

7. Salvar em IndexedDB:
   chave: `puzzle_program_${username}`
   valor: { ...puzzle_program, username, analyzed_at: new Date().toISOString() }

8. Retornar puzzle_program
```

**Sobre stockfish.js:** se o projeto já usa stockfish.js para outra feature, reutilizar a instância existente. Se não existe, adicionar `stockfish.js@10.0.2` (mesma versão do chess-scout-prototipo, testada e estável).

---

## Passo 4 — Integração na UI

- Campo username + botão "Gerar plano de treino"
- Progress bar por partida: "Analisando partida 12/30 (68%)"
- Badge de confiança tática ao lado do resultado:
  - `alta` → verde
  - `média` → amarelo
  - `baixa` → laranja
  - `insuficiente` → vermelho + mensagem "Jogue partidas rapid ou blitz para análise tática confiável"
- Lista de temas ordenada: `detected` primeiro (com ícone de "detectado nas suas partidas"), depois `rating`
- Cada tema com botão para iniciar treino daquele tema no Woodpecker
- Resultado cacheado em IndexedDB: ao reabrir, exibir resultado anterior com data + botão "Reanalisar"

---

## Critérios de done

- [ ] `tactical-themes.js` e `themes_index.json` copiados e carregando sem erro no console
- [ ] `analyzePlayer('username_de_teste')` retorna `puzzle_program` válido no console
- [ ] Temas com `source: 'detected'` aparecem antes dos de `source: 'rating'`
- [ ] `tactical_confidence.level` aparece na UI com badge colorido
- [ ] Se `level === 'insuficiente'`, mensagem clara ao usuário
- [ ] Resultado persiste em IndexedDB e é exibido sem re-análise ao reabrir
- [ ] Progress bar atualiza por partida durante a análise
- [ ] `analyzePlayer` aceita `onProgress(current, total)` callback

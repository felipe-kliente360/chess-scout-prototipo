// Classificação de temas táticos a partir de assinaturas posicionais (B) e
// de delta de lance (C). O índice é construído offline por
// scripts/build_tactical_index.py a partir do release woodpecker-puzzles.
// Aqui só recriamos o mesmo hash do Python e fazemos lookup.
//
// API pública:
//   loadTacticalIndex()  → fetch lazy do JSON, cacheado
//   classifyPosition(fen, bestUci?, playedUci?) → { theme, confidence, source }
//
// Implementação de attackers é manual (chess.js 0.10.3 não tem .attackers()).

(function (global) {
  "use strict";

  const TACTICAL_INDEX_URL = "data/tactical/themes_index.json";
  const PIECE_VALUE = { p: 1, n: 3, b: 3, r: 5, q: 9, k: 100 };
  const SYM_OF = { p: "P", n: "N", b: "B", r: "R", q: "Q", k: "K" };
  const HIGH_VALUE = new Set(["n", "b", "r", "q", "k"]);

  let TACTICAL_INDEX = null;
  let LOAD_PROMISE = null;

  async function loadTacticalIndex() {
    if (TACTICAL_INDEX) return TACTICAL_INDEX;
    if (LOAD_PROMISE) return LOAD_PROMISE;
    LOAD_PROMISE = (async () => {
      try {
        const res = await fetch(TACTICAL_INDEX_URL);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        TACTICAL_INDEX = await res.json();
        return TACTICAL_INDEX;
      } catch (e) {
        console.warn(`[tactical] índice não disponível: ${e.message}`);
        TACTICAL_INDEX = { B: {}, C: {}, version: 0 };
        return TACTICAL_INDEX;
      }
    })();
    return LOAD_PROMISE;
  }

  // ── Helpers de geometria ────────────────────────────────────────────
  function fileOf(sq) { return sq.charCodeAt(0) - 97; }       // 'a' → 0
  function rankOf(sq) { return parseInt(sq[1], 10) - 1; }     // '1' → 0
  function sqOf(f, r) { return String.fromCharCode(97 + f) + (r + 1); }
  function inBoard(f, r) { return f >= 0 && f < 8 && r >= 0 && r < 8; }
  function distance(a, b) {
    return Math.max(Math.abs(fileOf(a) - fileOf(b)), Math.abs(rankOf(a) - rankOf(b)));
  }

  // Lista de [piece, square] dada uma board() de chess.js 0.10.3
  function* allPieces(board2d) {
    for (let r = 0; r < 8; r++) {
      for (let f = 0; f < 8; f++) {
        const p = board2d[7 - r][f];
        if (p) yield [p, sqOf(f, r)];
      }
    }
  }

  function pieceAt(board2d, sq) {
    const f = fileOf(sq), r = rankOf(sq);
    return board2d[7 - r][f];
  }

  // attackers(board2d, sq, color): squares de peças `color` que atacam `sq`.
  // Reimplementa o que chess.is_attacked_by/python-chess attackers fazem.
  function attackersOf(board2d, sq, color) {
    const tf = fileOf(sq), tr = rankOf(sq);
    const out = [];

    // Peões: atacam diagonalmente para frente
    const pawnDir = color === "w" ? -1 : 1; // de onde vem o ataque (origem do peão)
    for (const df of [-1, 1]) {
      const f = tf + df, r = tr + pawnDir;
      if (!inBoard(f, r)) continue;
      const p = board2d[7 - r][f];
      if (p && p.type === "p" && p.color === color) out.push(sqOf(f, r));
    }

    // Cavalos
    const knightJumps = [[1,2],[2,1],[-1,2],[-2,1],[1,-2],[2,-1],[-1,-2],[-2,-1]];
    for (const [df, dr] of knightJumps) {
      const f = tf + df, r = tr + dr;
      if (!inBoard(f, r)) continue;
      const p = board2d[7 - r][f];
      if (p && p.type === "n" && p.color === color) out.push(sqOf(f, r));
    }

    // Rei
    for (let df = -1; df <= 1; df++) {
      for (let dr = -1; dr <= 1; dr++) {
        if (df === 0 && dr === 0) continue;
        const f = tf + df, r = tr + dr;
        if (!inBoard(f, r)) continue;
        const p = board2d[7 - r][f];
        if (p && p.type === "k" && p.color === color) out.push(sqOf(f, r));
      }
    }

    // Sliding: bispo/dama nas diagonais; torre/dama nas ortogonais
    const rays = [
      [[1,1],"bq"], [[1,-1],"bq"], [[-1,1],"bq"], [[-1,-1],"bq"],
      [[1,0],"rq"], [[-1,0],"rq"], [[0,1],"rq"], [[0,-1],"rq"],
    ];
    for (const [[df, dr], allowed] of rays) {
      let f = tf + df, r = tr + dr;
      while (inBoard(f, r)) {
        const p = board2d[7 - r][f];
        if (p) {
          if (p.color === color && allowed.includes(p.type)) out.push(sqOf(f, r));
          break;
        }
        f += df; r += dr;
      }
    }

    return out;
  }

  function isAttackedBy(board2d, sq, color) {
    return attackersOf(board2d, sq, color).length > 0;
  }

  // ── Componentes do fingerprint B ────────────────────────────────────
  function kingSafetyTag(board2d, color) {
    let kingSq = null;
    for (const [p, sq] of allPieces(board2d)) {
      if (p.type === "k" && p.color === color) { kingSq = sq; break; }
    }
    if (!kingSq) return "noking";
    const f = fileOf(kingSq);
    const side = f >= 5 ? "ks" : (f <= 2 ? "qs" : "mid");
    const enemy = color === "w" ? "b" : "w";
    let nAtk = 0;
    for (let df = -1; df <= 1; df++) {
      for (let dr = -1; dr <= 1; dr++) {
        if (df === 0 && dr === 0) continue;
        const nf = fileOf(kingSq) + df, nr = rankOf(kingSq) + dr;
        if (!inBoard(nf, nr)) continue;
        if (isAttackedBy(board2d, sqOf(nf, nr), enemy)) nAtk++;
      }
    }
    return `${side}_${nAtk}`;
  }

  function highValueAttacks(board2d, attackerColor) {
    const enemy = attackerColor === "w" ? "b" : "w";
    const attacks = [];
    for (const [target, sq] of allPieces(board2d)) {
      if (target.color !== enemy) continue;
      if (!HIGH_VALUE.has(target.type)) continue;
      const atks = attackersOf(board2d, sq, attackerColor);
      if (!atks.length) continue;
      const defs = attackersOf(board2d, sq, enemy);
      const nDef = defs.length;
      for (const aSq of atks) {
        const aP = pieceAt(board2d, aSq);
        if (!aP) continue;
        attacks.push([SYM_OF[aP.type], SYM_OF[target.type], nDef, PIECE_VALUE[target.type]]);
      }
    }
    attacks.sort((a, b) => (b[3] - a[3]) || a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]));
    return attacks.slice(0, 4);
  }

  function undefendedHighValue(board2d, color) {
    const out = [];
    for (const [p, sq] of allPieces(board2d)) {
      if (p.color !== color) continue;
      if (!HIGH_VALUE.has(p.type)) continue;
      if (attackersOf(board2d, sq, color).length === 0) {
        out.push([SYM_OF[p.type], PIECE_VALUE[p.type]]);
      }
    }
    out.sort((a, b) => (b[1] - a[1]) || a[0].localeCompare(b[0]));
    return out.slice(0, 4).map(x => x[0]);
  }

  function openFilesNearKing(board2d, color) {
    let kingSq = null;
    for (const [p, sq] of allPieces(board2d)) {
      if (p.type === "k" && p.color === color) { kingSq = sq; break; }
    }
    if (!kingSq) return 0;
    const kingFile = fileOf(kingSq);
    const filesW = new Array(8).fill(0);
    const filesB = new Array(8).fill(0);
    for (const [p, sq] of allPieces(board2d)) {
      if (p.type !== "p") continue;
      const f = fileOf(sq);
      if (p.color === "w") filesW[f]++; else filesB[f]++;
    }
    let n = 0;
    for (let f = Math.max(0, kingFile - 2); f < Math.min(8, kingFile + 3); f++) {
      if (filesW[f] === 0 || filesB[f] === 0) n++;
    }
    return n;
  }

  // ── Fingerprints ────────────────────────────────────────────────────
  function fingerprintB(chess) {
    const board2d = chess.board();
    const stm = chess.turn();             // 'w' ou 'b'
    const enemy = stm === "w" ? "b" : "w";
    const ks = kingSafetyTag(board2d, stm);
    const eks = kingSafetyTag(board2d, enemy);
    const atks = highValueAttacks(board2d, stm)
      .map(([a, t, d]) => `${a}>${t}_d${d}`).join(";");
    const undef = undefendedHighValue(board2d, enemy).join(";");
    const openF = openFilesNearKing(board2d, enemy);
    return `${stm}|sk_${ks}|ek_${eks}|${atks}|U:${undef}|of_${openF}`;
  }

  // Aplica um lance UCI a uma cópia e devolve o novo Chess. null se ilegal.
  function applyUciCopy(chess, uci) {
    const c2 = new Chess(chess.fen());
    const m = c2.move({
      from: uci.slice(0, 2),
      to: uci.slice(2, 4),
      promotion: uci.length > 4 ? uci.slice(4) : undefined,
    });
    return m ? c2 : null;
  }

  function fingerprintC(chess, bestUci) {
    const solver = chess.turn();
    const enemy = solver === "w" ? "b" : "w";
    const before = chess.board();

    // Pre attacks: solver atacando peças HIGH_VALUE inimigas
    const pre = new Set();
    for (const [p, sq] of allPieces(before)) {
      if (p.color !== enemy || !HIGH_VALUE.has(p.type)) continue;
      for (const aSq of attackersOf(before, sq, solver)) {
        const aP = pieceAt(before, aSq);
        if (aP) pre.add(`${SYM_OF[aP.type]}|${SYM_OF[p.type]}|${sq}`);
      }
    }

    // Captura: peça inimiga em best.to ANTES do lance
    const toSq = bestUci.slice(2, 4);
    const capPiece = pieceAt(before, toSq);
    const captured = (capPiece && capPiece.color === enemy) ? SYM_OF[capPiece.type] : "";

    const after = applyUciCopy(chess, bestUci);
    if (!after) return null;
    const isCheck = after.in_check();
    const isMate = after.in_checkmate();
    const after2d = after.board();

    const post = new Set();
    for (const [p, sq] of allPieces(after2d)) {
      if (p.color !== enemy || !HIGH_VALUE.has(p.type)) continue;
      for (const aSq of attackersOf(after2d, sq, solver)) {
        const aP = pieceAt(after2d, aSq);
        if (aP) post.add(`${SYM_OF[aP.type]}|${SYM_OF[p.type]}|${sq}`);
      }
    }

    // Gained = post - pre
    const gained = [];
    for (const k of post) if (!pre.has(k)) gained.push(k);

    // Compacta para (atacante, alvo) deduplicado, top 5 ordenado
    const compactSet = new Set();
    let targetUndef = 0;
    for (const k of gained) {
      const [a, t, sq] = k.split("|");
      compactSet.add(`${a}>${t}`);
      if (attackersOf(after2d, sq, enemy).length === 0) targetUndef = 1;
    }
    const targets = new Set();
    for (const at of compactSet) targets.add(at.split(">")[1]);
    const compactList = Array.from(compactSet).sort().slice(0, 5);
    const gainStr = compactList.join(",");

    return (`g:${gainStr}|nT:${targets.size}|cap:${captured}` +
            `|chk:${isCheck ? 1 : 0}|mate:${isMate ? 1 : 0}|tU:${targetUndef}`);
  }

  // ── API de classificação ────────────────────────────────────────────

  // Retorna top-3 temas com confiança >= minConf. null se nenhum match.
  function lookupMulti(table, fp, minN, minConf) {
    if (!table || !fp) return null;
    const hit = table[fp];
    if (!hit || !hit.t || !hit.t.length || hit.n < minN) return null;
    const themes = [];
    for (let i = 0; i < Math.min(hit.t.length, 3); i++) {
      const conf = Math.round((hit.c[i] / hit.n) * 100) / 100;
      if (conf < minConf) break;
      themes.push({ theme: hit.t[i], confidence: conf });
    }
    if (!themes.length) return null;
    return { themes, n: hit.n };
  }

  function classifyPosition(fen, bestUci, playedUci) {
    if (!TACTICAL_INDEX) return null;
    let chess;
    try { chess = new Chess(fen); } catch (_) { return null; }

    // C tem prioridade quando temos best_move (delta é mais discriminante)
    if (bestUci && bestUci.length >= 4) {
      try {
        const fpC = fingerprintC(chess, bestUci);
        const hit = lookupMulti(TACTICAL_INDEX.C, fpC, 5, 0.30);
        if (hit) {
          return {
            // legado: theme/confidence apontam para top-1
            theme: hit.themes[0].theme,
            confidence: hit.themes[0].confidence,
            n: hit.n,
            // novo: array completo top-3
            themes: hit.themes,
            source: "C",
            fingerprint: fpC,
          };
        }
      } catch (_) { /* fallback B */ }
    }

    // B como fallback (ou primário se não há best_move)
    try {
      const fpB = fingerprintB(chess);
      const hit = lookupMulti(TACTICAL_INDEX.B, fpB, 3, 0.30);
      if (hit) {
        return {
          theme: hit.themes[0].theme,
          confidence: hit.themes[0].confidence,
          n: hit.n,
          themes: hit.themes,
          source: "B",
          fingerprint: fpB,
        };
      }
    } catch (_) {}
    return null;
  }

  // Exporta para o escopo global (consumido por index.html)
  global.TacticalThemes = {
    loadTacticalIndex,
    classifyPosition,
    computeFingerprintB: (fen) => {
      try { return fingerprintB(new Chess(fen)); } catch (_) { return null; }
    },
    computeFingerprintC: (fen, bestUci) => {
      try { return fingerprintC(new Chess(fen), bestUci); } catch (_) { return null; }
    },
  };
})(typeof window !== "undefined" ? window : globalThis);

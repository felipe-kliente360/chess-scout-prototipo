# Apoio teórico — relatórios de xadrez

Este documento é referência obrigatória para quem redige as seções narrativas das skills `report-myself` e `report-enemy`. Use os conceitos e faixas daqui para sustentar afirmações; cite números do JSON computado em vez de adjetivos vagos.

---

## 1. Como ler o Score (0–10) — calibrado por depth e rating

**Score 10** mede **performance vs. expectativa para o seu rating**, não acurácia absoluta. Calibrado por dois ajustes:

1. ACPL medido é normalizado para o equivalente em depth 20 (motor mais raso encontra menos erros — `depth_factor`).
2. Comparado ao ACPL típico esperado para a faixa de rating do jogador (`expected_acpl(rating) = 130 * exp(-rating/1200)`).

Fórmula final: `score = 10 * exp(-(acpl_d20 / expected_acpl) / 2)`. Calculado no JSON em `c.kpis.score_10`, `c.by_phase[*].score_10`, etc. **Não cite ACPL no texto narrativo** — sempre Score.

Glose única ao introduzir: *"score de 0 a 10 que compara seu nível de erro com o esperado para o seu rating — 6 = jogou como esperado, acima = jogou melhor, abaixo = jogou pior"*. Use **uma vez** na Seção 1 e nunca mais explique.

| Score | Leitura |
|---|---|
| 9.0 – 10 | Muito acima do esperado para o rating (4x+ melhor que típico) |
| 7.5 – 9.0 | Bem acima do esperado (2x melhor) |
| 6.0 – 7.5 | Levemente acima do esperado |
| **5.5 – 6.5** | **Baseline — jogou como esperado para o rating** |
| 4.0 – 5.5 | Levemente abaixo do esperado |
| 2.5 – 4.0 | Bem abaixo do esperado (2x pior) |
| < 2.5 | Muito abaixo (3x+ pior) |

**Cuidados:**
- Score 9+ sistemático em Rapid pode indicar dado anômalo: rating subestimado, ou Daily/análise com tempo extra inflando o resultado. Confirme no `score_calibration.performance_ratio` (quanto menor que 1.0, mais "acima do esperado").
- Em bullet, o score continua relativo, mas o `expected_acpl` da fórmula assume tempos longos — então scores de bullet ficam artificialmente baixos. Mencione.
- O bloco `c.score_calibration` no JSON expõe rating usado, depth_factor aplicado, ACPL observado vs. ACPL esperado, e o ratio — use para auditar afirmações.
- ACPL existe no JSON só para auditoria. **Use sempre Score no texto.**

## 1b. Confiança estatística (`confidence_pct`)

Índice 0–100% no JSON em `c.sample_quality.confidence_pct`. Combina três fatores: amostra (50%), profundidade do motor (30%), cobertura ECO (20%). Use na seção 1 para calibrar quão fortes podem ser as afirmações:

| % | Leitura |
|---|---|
| < 40 | Tendência apenas; evite afirmações categóricas |
| 40 – 70 | Padrões começam a aparecer; cuidado com sub-amostras pequenas (cor, ECO) |
| 70 – 90 | Conclusões fortes permitidas |
| > 90 | Diagnóstico robusto em todas as dimensões |

---

## 2. Categorias de erro

Os limiares usados no `compute.py` (em centipeões perdidos vs. melhor lance):

| Categoria | Faixa | O que significa |
|---|---|---|
| **Blunder** | ≥ 300 cp | Erro grave — geralmente perde material ou troca a avaliação completamente |
| **Mistake** | 100 – 299 cp | Erro de cálculo ou plano que entrega vantagem clara |
| **Imprecisão** | 50 – 99 cp | Lance posicional subótimo, sem perda imediata, mas que abre desconforto |
| **Boa** | < 50 cp | Lance dentro da margem aceitável |

Atenção: um único blunder por partida é normal até ~1800. Acima disso, a curva cai rápido — mestres têm partidas inteiras sem blunder algum. Já a quantidade de mistakes diz mais sobre **calibração estratégica** do que sobre falta de atenção: 4 mistakes sem blunder normalmente indica "joga limpo mas não faz pressão".

---

## 3. Análise por fase

Limiares no `compute.py`: abertura = lances 1–20, final = últimos 20 lances, meio-jogo = entre eles.

**Padrões clássicos de fragilidade por fase:**

- **Abertura ruim** → o jogador não estudou repertório formal. Sai do livro cedo, perde tempo, dá centro. Solução: 8–10 lances decorados de uma resposta a 1.e4 e 1.d4 com brancas e pretas.
- **Meio-jogo ruim** → cálculo concreto fraco, ou avaliação estratégica desorganizada. Solução: táticas diárias + estudo de planos típicos (estruturas de peões, ataques no rei).
- **Final ruim** → falta de finais teóricos básicos (Lucena, Philidor, oposição, regra do quadrado). Solução: estudar 5–10 finais canônicos antes de ir para finais práticos.
- **Tudo equilibrado, mas perde** → não é problema de precisão, é de **iniciativa**. O jogador faz lances corretos mas reativos; o adversário acumula pequenas vantagens posicionais. Solução: estudar sacrifícios temáticos, entender quando arriscar.

**Heurística de leitura cruzada:** se ACPL geral é bom mas win-rate é ruim, a causa quase sempre está em meio-jogo (ausência de iniciativa) ou em transições entre fases (lances bons isolados, mas plano inconsistente).

---

## 4. Cor: o que a assimetria conta

Comparar performance com brancas vs pretas é diagnóstico de repertório, não de talento.

- **Brancas pior que pretas** → jogador não tem plano agressivo; está mais confortável reagindo. Tipicamente prepara variantes pretas mas vai "no improviso" com brancas.
- **Pretas pior que brancas** → repertório de defesa pobre; provavelmente sofre contra aberturas específicas (1.e4 ou 1.d4).
- **Diferença grande em ACPL mas similar em win-rate** → uma cor joga preciso e perde, outra joga sujo e ganha. Isso é diagnóstico de **conversão**: em uma cor o jogador é técnico mas passivo; na outra é caótico mas competitivo.

Não comente assimetria de cor com amostras < 8 partidas por cor. Antes disso, é ruído.

---

## 5. Tamanho da amostra e profundidade

**Tamanho da amostra (n_games):**

| n | Tier de confiabilidade |
|---|---|
| < 10 | **Preliminar** — apenas tendências grosseiras, evite afirmações categóricas |
| 10 – 29 | **Adequado** — padrões começam a se firmar; cuidado com cor, ECO e adversários |
| ≥ 30 | **Robusto** — comparações por fase, cor e adversário ficam estatisticamente úteis |

**Profundidade do motor (depth):**

| Depth | Confiabilidade |
|---|---|
| < 10 | Não confie em magnitude de erros; só ranking grosseiro |
| 10 – 14 | Aceitável para detectar blunders e mistakes |
| ≥ 15 | Confiável para magnitude de imprecisões e nuances posicionais |
| ≥ 18 | Padrão para análise séria; usado em coach reports profissionais |

**Regra prática:** se `tier == "preliminar"`, a seção 11 deve recomendar primeiro **rodar mais partidas com depth maior** antes de qualquer outra prescrição. Conclusões fortes com amostra fraca são o erro mais comum em relatórios automatizados.

---

## 5b. Profundidade de teoria (`avg_eco_ply`)

A base ECO do Lichess (3.690 posições) classifica cada partida pela última posição reconhecida na varredura dos primeiros 25 plies. `avg_eco_ply` é a média de até onde o jogador "ficou no livro" antes de improvisar.

| avg_eco_ply | Leitura |
|---|---|
| < 5 | Improviso desde o início — sem repertório |
| 5 – 10 | Repertório casual; provavelmente segue padrões intuitivos sem ter estudado |
| 10 – 15 | Repertório estudado; conhece linhas principais |
| > 15 | Repertório profissional; segue teoria moderna profundamente |

Use junto com win-rate da família:
- **Profundidade alta + win-rate alto** → repertório dominado, evite (perspectiva enemy) ou capitalize (myself).
- **Profundidade alta + win-rate baixo** → segue teoria mas não converte; vulnerabilidade no meio-jogo após a abertura.
- **Profundidade baixa + win-rate alto** → joga por intuição e ganha; depende do cenário familiar — induza o oposto.
- **Profundidade baixa + win-rate baixo** → fora do livro logo; pressionar técnico desde o lance 6 derruba.

`openings_weak_spots` no JSON lista famílias com `n ≥ 5` e win-rate < 40%. Em `report-myself` viram alvos de estudo; em `report-enemy` viram alvos de indução.

---

## 6. Win-rate vs precisão — quando divergem

Quatro combinações possíveis:

1. **Alta precisão + alto win-rate** → jogador competitivo e técnico. Próximo passo: subir nível de adversário.
2. **Alta precisão + baixo win-rate** → "joga limpo, mas perde". Falta iniciativa, ou enfrenta adversários acima do próprio nível. Diagnóstico mais comum em jogadores 1400–1800 que estudam táticas mas não estratégia.
3. **Baixa precisão + alto win-rate** → ganha por força tática contra adversários piores. Frágil contra oponentes mais fortes; teto baixo se não estabilizar fundamentos.
4. **Baixa precisão + baixo win-rate** → fundamentos faltando em tudo. Foco: básico de tática (ataques duplos, espetos, descobertas) e finais elementares.

Use essa matriz na seção 11 (plano de ação): cada quadrante tem prescrição diferente.

---

## 7. Finais teóricos relevantes

Conceitos que devem estar dominados antes de subir de faixa:

- **Rei + Torre vs Rei** (mate técnico) — base.
- **Lucena** — torre no flanco, peão prestes a coroar; torre adversária na coluna oposta. Procedimento: construir "ponte".
- **Philidor** — defesa contra peão+torre+rei adversários; chave é manter a torre na 6ª/3ª fila.
- **Oposição direta** em finais de rei e peão.
- **Regra do quadrado** — saber se o rei alcança um peão passado.
- **Final de bispos de cores opostas** — frequentemente empate mesmo com 2 peões a mais.

Se a partida paradigmática termina em final teórico clássico mal conduzido, **cite o nome do final** (Lucena, Philidor) na narrativa. Isso ancora o aprendizado.

---

## 8. Padrões por faixa de rating (chess.com)

| Faixa | Característica dominante |
|---|---|
| < 1000 | Erros táticos diretos: peças penduradas, mate em 1, falta de desenvolvimento |
| 1000–1400 | Cálculo de 1–2 lances OK, mas falha em planos longos; aberturas pelo improviso |
| 1400–1800 | Repertório formal começa; meio-jogo razoável; finais e estratégia ainda fracos |
| 1800–2200 | Técnica sólida em todas as fases; falha contra forte cálculo concreto e em transições |
| 2200+ | Diferenças sutis: profilaxia, manobras lentas, cálculo de 6+ lances |

Ao redigir, situe o jogador na faixa observada (use rating médio de adversários como proxy se o rating próprio não estiver no JSON) e descreva os obstáculos típicos *daquela faixa*. Não recomende profilaxia para um 1100; recomende não pendurar peças.

---

## 9. Vocabulário em linguagem direta

Conceitos técnicos a usar **com tradução**, sem assumir que o leitor conhece:

- **Iniciativa**: quem dita o ritmo, força respostas. "Tomar a iniciativa" = forçar o adversário a defender.
- **Profilaxia**: jogar pensando primeiro no plano do adversário e neutralizá-lo. Antônimo: jogar só seu próprio plano.
- **Restrição**: limitar movimento das peças adversárias antes de atacar.
- **Tempo (em xadrez)**: cada lance é um tempo. Perder tempo = mover a mesma peça duas vezes sem ganho, ou fazer um lance que o adversário ignora.
- **Espaço**: peões avançados controlam casas. Mais espaço = mais opções de manobra.
- **Estrutura de peões**: o "esqueleto" da posição. Define plano estratégico (ataque de minoria, peão isolado, peão passado, etc.).
- **Transição de fase**: momento em que a posição muda de caráter (abertura→meio-jogo após desenvolvimento; meio-jogo→final após troca de damas). Crítico — muitos erros acontecem aqui.
- **cp / centipeão**: 1/100 de peão. Avaliações do motor. +100 cp ≈ vantagem de um peão.

Sempre que usar um desses termos pela primeira vez no relatório, faça uma micro-glosa entre travessões. Exemplo: "miguelrov perde *iniciativa* — controle do ritmo da partida — em transições para o final."

---

## 10. Estrutura sugerida das seções narrativas (mapeamento direto com números)

Cada seção deve abrir com **um fato numérico do JSON** e fechar com **uma implicação prática**. Exemplo:

> "Abertura: score 8,4/10. Concentra o único erro grave da amostra. Implicação prática: estudar 8 lances de uma resposta padrão a 1.e4 corrige isso em uma semana."

Evite:
- Frases sem número.
- Adjetivos sem comparação (ex: "bom", "alto", "preocupante" — comparado a quê?).
- Aberturas pomposas ("Este relatório busca examinar...", "É notório que..."). Vá direto ao ponto.
- Vocabulário ostensivo quando há sinônimo simples ("cartografia estratégica" → "padrões de jogo"; "engenharia dos finais" → "como conduz finais").

A meta é: **um leigo culto entende, um enxadrista experiente concorda.**

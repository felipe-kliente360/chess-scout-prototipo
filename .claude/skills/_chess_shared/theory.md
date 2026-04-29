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

---

## 11. Biblioteca de motivos táticos (cite pelo nome quando detectar)

Use os nomes canônicos. Cada motivo tem **pista de detecção** para identificar nas partidas paradigmáticas. Quando o `worst_move` ou um lance decisivo couber num desses padrões, **cite pelo nome** — ancora o aprendizado e dá autoridade.

| Motivo | Definição em uma frase | Pista de detecção |
|---|---|---|
| **Cravada** (pin) — absoluta vs. relativa | Peça presa que não pode mover sem expor uma peça mais valiosa atrás dela | Bispo/torre/dama na mesma linha que duas peças adversárias, sendo a de trás mais valiosa |
| **Espeto** (skewer) | Como cravada, mas a peça de trás é a mais valiosa e tem que sair | Frequente em finais de torres |
| **Garfo** (fork) — cavalo, dama, peão, rei | Uma peça ataca duas ou mais ao mesmo tempo | Cavalo no meio do tabuleiro (e5, d5) frequentemente garfa |
| **Ataque descoberto** (discovered attack) | Mover uma peça revela ataque de outra atrás dela | Frequente em posições com bispo/torre na mesma fila/coluna que peça adversária valiosa |
| **Xeque duplo** (double check) | Duas peças dão xeque ao mesmo tempo — rei obrigado a mover | Devastador, geralmente leva a mate ou ganho material |
| **Remoção do defensor** (removing the defender) | Captura ou afasta a peça que protege uma fraqueza | Procurar peça defendida só uma vez |
| **Desvio** (deflection) | Força peça a sair da função defensiva | Lance forçante (xeque, captura) que tira o defensor |
| **Isca** (decoy) | Atrai peça adversária para casa ruim com sacrifício | Comum em ataques ao rei |
| **Interferência** (interference) | Peça menor entra entre duas adversárias quebrando coordenação | Mais raro, mas elegante |
| **Sobrecarga** (overloading) | Peça defendendo dois alvos ao mesmo tempo, removida de um perde o outro | Damas e torres tipicamente sobrecarregadas |
| **Peça presa** (trapped piece) | Peça sem casas legais ou seguras de fuga | Cavalo no canto, bispo após ...g6 contra Bxh6 |
| **Zwischenzug** (lance intermediário) | Insere lance forçante (xeque ou ameaça) antes do esperado, mudando o cálculo | Quase sempre xeque ou captura inesperada |
| **Desperado** | Peça condenada vai vender caro a vida | "já que vai morrer, leva alguém junto" |
| **Bateria** (battery) | Duas peças alinhadas na mesma direção — dama+bispo, torre+torre | Concentra força numa linha |
| **X-ray** | Peça atrás de outra que pode "ver através" se a da frente sair | Próximo ao conceito de cravada/espeto |
| **Ataque duplo** (double attack) | Conceito-pai: qualquer lance que crie duas ameaças simultâneas | Garfo é um caso particular |
| **Mate da fila do fundo** (back rank) | Mate por torre/dama na 1ª/8ª linha contra rei sem fuga | Procurar rei roque-curto sem janela de peão recuado |
| **Mate sufocado / Philidor** (smothered) | Cavalo dá mate com peças próprias bloqueando o rei | Sequência clássica: Cf7+ Rg8 Ch6+ Rh8 Dg8+ Txg8 Cf7# |
| **Sacrifício grego** (Greek gift, Bxh7+/Lxh7+) | Sacrifício de bispo em h7 contra rei roque-curto | Padrão "clássico": peões e2-e3-e5 brancos, dama em c2/d3, cavalo em f3 |
| **Mate de Anastasia** | Cavalo+torre matando rei na 8ª (ou 1ª) com peão próprio bloqueando | Ce7+ + torre na lateral |
| **Mate de Boden** | Dois bispos cruzados matando rei castelado | Após sacrifício em a3/h3 |
| **Mate árabe** | Cavalo+torre, torre dá mate, cavalo guarda fuga | Comum em finais |
| **Catavento** (windmill) | Sequência de descobertos consecutivos | Lendário: Torre+Bispo |

**Como usar na narrativa:** "No ply 34 vs Schmucki1, jogou Rb4 — perdeu a oportunidade de Rxa6 (espeto contra o rei adversário em a8 e a torre em a4)."

---

## 12. Biblioteca de conceitos estratégicos posicionais (use o nome canônico)

Conceitos do livro de Soltis ("Pawn Structure Chess") e Kmoch ("Pawn Power in Chess"). Quando o JSON tem `position_features` indicando uma das estruturas abaixo, **cite pelo nome** e descreva o tratamento clássico.

### Estruturas de peões (esqueleto da posição)
- **Peão dama isolado / IQP** (peão branco em d4 sem c-peão, ou preto em d5 sem c-peão): vantagem dinâmica para o lado que tem (atividade, casas e4/e5/c5), desvantagem estática (peão fraco a longo prazo). Lado fraco: bloquear em d5/d4 com cavalo, trocar peças, simplificar. Lado forte: atacar antes do final.
- **Peões pendurados / hanging pawns** (par de peões c+d ou e+f sem peões adjacentes): força dinâmica enquanto avançam juntos; fraqueza estrutural se forçados a parar. Tratamento: avançar (c5 ou d5) na hora certa; lado contrário busca bloqueio.
- **Peão atrasado** (backward pawn): peão que não pode avançar com segurança. Casa à frente vira ponto fraco. Lado fraco: trocar; lado forte: ocupar a casa com peça.
- **Peões dobrados**: perde flexibilidade, mas abre coluna semi-aberta para a torre. Compensação se houver controle dessa coluna.
- **Peão passado** (passed pawn): peão sem peões adversários na sua coluna ou nas adjacentes na frente. Cresce em valor conforme avança. **Princípio Nimzowitsch**: "peão passado deve ser bloqueado, idealmente por cavalo".
- **Peão passado protegido** (protected passed pawn): peão passado defendido por outro peão. Vantagem decisiva na maioria dos finais.
- **Ilhas de peões** (pawn islands): grupos de peões separados. Menos ilhas = estrutura mais saudável.
- **Cadeia de peões** (pawn chain): peões diagonais conectados (ex: e4-d3 brancos). Tratamento: atacar a base, não a cabeça.
- **Alavanca de libertação** (liberation lever, Kmoch): movimento de ruptura de peão (ex: c5 contra IQP) que altera a estrutura abruptamente.

### Conceitos posicionais não-estruturais
- **Avanço/posto** (outpost): casa apoiada por peão próprio onde adversário não pode atacar com peão. Cavalo avançado em outpost (ex: cavalo branco em d5 com peão em c4 ou e4) vale uma menor.
- **Casa fraca** (weak square): casa que adversário não pode mais atacar com peão. Vira posto natural.
- **Debilidade de cor** (color complex weakness): faltam peões de uma cor → diagonais dessa cor ficam vulneráveis. Frequente após ...g6 sem bispo de casas pretas.
- **Coluna aberta**: sem peões. Domínio = torre dobrada, depois 7ª fila.
- **Coluna semi-aberta**: sem seu peão, com adversário. Boa para pressão.
- **Par de bispos vs par de cavalos**: par de bispos vale ~0.5 peão a mais em posições abertas; cavalos preferem posições fechadas.
- **Bispo mau** (bad bishop): bispo bloqueado pelos próprios peões na cor dele. Ex: bispo de casas pretas com peões em e6/d5/c6 nas casas pretas.
- **Bispo bom** (good bishop): bispo com diagonais livres.
- **Ataque de minoria** (minority attack): poucos peões avançam contra muitos para criar fraquezas. Clássico: brancos com peões em a2/b2 contra pretos com a7/b7/c6 — brancos jogam b4-b5 para criar peão fraco em c6.
- **Princípio das duas fraquezas** (Capablanca/Karpov): para vencer posição igual, crie segunda fraqueza no flanco oposto. Adversário não consegue defender ambos.
- **Restrição** (restriction, Petrosian): limitar mobilidade adversária antes de atacar. h3/a3 para negar casas de cavalo.
- **Profilaxia** (prophylaxis, Nimzowitsch → Dvoretsky): prever plano adversário e neutralizar antes. Ver §15.
- **Sacrifício de qualidade** (exchange sacrifice): trocar torre por menor por compensação posicional. Estilo Petrosian.
- **Iniciativa**: ditar o ritmo, forçar respostas. Vale mais que material em curto prazo.

---

## 13. As 7 técnicas posicionais magistrais

Síntese de Karpov, Botvinnik, Petrosian, Alekhine, Capablanca, Carlsen. Quando uma partida paradigmática se encaixa numa destas, **cite pelo nome**.

1. **Otimização Posicional Absoluta** (Karpov): cada peça na sua casa ideal antes de operação tática. Princípio: melhorar a pior peça primeiro. Sintoma de jogador 1500–1800 que falha aqui: peças desenvolvem para casas "naturais" (Cf3, Bc4) sem reavaliar se ainda são ótimas após o adversário se desenvolver.
2. **Hegemonia do Centro Expandido**: controle de pelo menos 2 das 4 casas centrais (d4-e4-d5-e5) + influência sobre o "grande centro" (c3-c6-f3-f6). Operações nos flancos só após centro estabilizado.
3. **Pressão Contínua nas Fraquezas**: ao identificar/criar fraqueza posicional, todas as peças convergem para pressioná-la. Não é apenas sobre material — é sobre forçar o adversário a defender perpetuamente, drenando energia mental.
4. **Provocação Profilática e Psicológica**: induzir o adversário a criar fraquezas desnecessárias (ex: forçar h6 ou a6 desnecessários). "Aparência de agressão sem material em jogo, gerando erros espontâneos."
5. **Asfixia Posicional e Restrição** (Petrosian, Botvinnik): suprimir contrajogo até zero. Permite executar planos próprios com simplicidade clínica. O adversário fica sem ar e não tem como buscar tática.
6. **Lances de Propósito Múltiplo e Regra das Duas Fraquezas** (Alekhine): operar em ambos os flancos simultaneamente. Quando um lance só serve a um plano, é fraco; quando serve a dois, é magistral.
7. **Transição Cirúrgica para Finais Técnicos Ganhos**: trocar peças no momento certo, ciente de que defeitos estruturais (peão dobrado, isolado, bispo mau) viram fatais em finais. **Carlsen é o paradigma vivo** disso.

---

## 14. Estruturas de peões clássicas — atalhos de plano

Por trás de toda abertura há uma estrutura típica. Conhecer a estrutura = saber o plano sem calcular.

| Estrutura | Aberturas que geram | Plano padrão |
|---|---|---|
| **Carlsbad** (peão branco em c3/d4/e3, preto em c6/d5/e6) | Defesa Damiana, QGD Exchange | Brancas: ataque de minoria b4-b5. Pretas: ataque ao rei com cavalos centrais. |
| **Tipo IQP** | Ataque Tarrasch, certas linhas QGA | Lado com IQP: peças ativas, ataque ao rei. Lado contrário: bloqueio em d4/d5, simplificação. |
| **Estonado** (peões e+d adversários travados) | Francesa Avançada, Caro-Kann Avançada | Brancas: flanco-rei (f4-f5). Pretas: flanco-dama (c5, contra ataque na base). |
| **Maroczy Bind** (brancas com c4+e4) | Siciliana Acelerada, Inglesa | Brancas controlam d5, espaço imenso. Pretas: trocar peças, buscar rupturas (...b5 ou ...d5). |
| **Stonewall** (peões em c3/d4/e3/f4 ou c6/d5/e6/f5) | Holandesa Stonewall, Caro-Kann Stonewall | Lado branco: ataque ao rei pelo flanco-rei (Cf3-Ce5). Casa e5/e4 imbatível. |
| **King's Indian formation** (pretas com d6+e5+g6) | Defesa Índia do Rei | Pretas: ataque ao rei (f5-f4-g5-g4). Brancas: flanco-dama (c5, b4). |
| **Defesa Berlim** (final de damas trocadas cedo) | Berlim Wall (Lopez) | Manobras lentas, valoriza par de bispos. |

Quando o JSON mostra família de abertura recorrente, **cite a estrutura típica e o plano correspondente** em vez de só nomear a abertura.

---

## 15. Profilaxia (Nimzowitsch → Dvoretsky) — ferramenta de elite

Técnica que separa 1800 de 2200. Hoje no `theory.md` aparecia só como vocabulário; aqui detalhada.

**Versão Nimzowitsch (clássica, "Mein System")**:
- Antecipar plano adversário antes de mexer suas peças.
- **Supercontrole**: sobrepoteger pontos fortes próprios (ex: e4 protegido 3x).
- **Restrição sistemática**: avançar peões marginais (h3, a3) para negar casas a cavalos adversários.

**Versão Dvoretsky (moderna, "School of Future Champions")**:
- Pergunta cética: *"Se meu oponente pudesse jogar 2 lances seguidos sem oposição, qual seria a configuração ideal dele nesta estrutura?"*
- Visualizando o design ótimo do inimigo, o jogador age **antes** que ele organize, não em reação.

**Quando invocar na narrativa:**
- Jogador comete erro porque ignorou ameaça que adversário poderia montar (não montou ainda) → "**Falta profilaxia**: o jogador não anteciperou que ..."
- Adversário dominou via supercontrole/restrição → "Nimzowitsch chamaria isso de **asfixia posicional**: o adversário restringiu sistematicamente as casas de cavalo do jogador (h3, a3) antes de qualquer operação ativa."

Para faixas <1500, **não recomende profilaxia** — é técnica de 1800+. Para 1500–1800, mencione como "próximo nível". Para 1800+, use ativamente.

---

## 16. Teoria dos Plys (Kuljasevic) — método estruturado de cálculo

Usar quando o JSON mostra padrão de erro tático recorrente.

**Etapa 1 — 1-Ply (Lances Candidatos)**:
- Mapear todos os lances pertinentes ANTES de calcular qualquer um.
- **Hierarquia obrigatória**: xeques > capturas > ameaças de mate > lances forçantes posicionais > lances quietos.
- Iniciar pela árvore de lances forçantes evita capivaras e economiza tempo.

**Etapa 2 — 2-Ply (Pensamento Cético)**:
- Para cada candidato, perguntar: "qual é a MELHOR resposta do adversário?"
- Buscar ativamente o recurso mais pernicioso (zwischenzug, contra-ataque, sacrifício de desvio).
- "Pensamento cético" = postura mental hostil às próprias ideias.

**Onde os 1500–2000 perdem partidas ganhas**: no ponto cego do 2-Ply. Otimismo + wishful thinking = ignoram a melhor refutação.

**Quando invocar**: derrota onde jogador montou combinação que o adversário refutou com lance "óbvio" que ele não viu. "Falha de **2-Ply**: você calculou Cd5 confiando que o adversário tomaria com peão (cxd5), mas a refutação Cxe7+ era xeque — sempre verificar xeques primeiro."

---

## 17. Vieses cognitivos — diagnosticar e nomear

Quando uma derrota não tem causa técnica óbvia, frequentemente é viés cognitivo. Liste os 4 principais:

1. **Viés do otimismo / cegueira tática**: jogador se apaixona pela própria combinação, calcula só as variantes que "funcionam". Sintoma: derrota com sacrifício injustificado nos lances 15–25.
2. **Viés de confirmação / ancoragem**: estrutura mudou, mas jogador segue plano original. Sintoma: ataque ao rei após o adversário trocar damas (não há mais ataque possível, mas continua jogando como se houvesse).
3. **Hubris / aversão à perda**: depois de sacrifício mal-sucedido, jogador insiste em mais sacrifícios para "justificar" o primeiro em vez de recuar. Sintoma: cascata de erros piores depois do erro inicial.
4. **Efeito emocional / complacência**: posição vencedora afrouxa atenção. "É exatamente neste vale de relaxamento mental em posições ditas 'ganhas' que as capivaras magistrais ocorrem." Sintoma: blunder no lance 35+ de uma partida que estava 80% vencida.

**Como usar**: quando a partida paradigmática de derrota mostra padrão consistente com um destes vieses, **cite o viés pelo nome**. "Esta partida é um caso clássico de **viés do otimismo**: ..."

**Para o redator de `report-myself`**: indicar exercício prático contra o viés diagnosticado — ex: para otimismo, tarefa "antes de cada sacrifício, escrever no caderno 3 motivos que o adversário pode usar para refutar".

---

## 18. Currículo 45-45-10 (referência para Seção 11 / plano de estudo)

Framework canônico para jogadores 1500–2000 buscando título FIDE. Em `report-myself` Seção 11, ancorar prescrições nessa proporção:

- **45% Estudo** — absorção de novos conceitos, repertório, táticas (Yusupov, Aagaard), estudos de finais (Dvoretsky).
- **45% Prática** — partidas reais (mínimo 1 séria/semana, rapid ou clássico — não bullet).
- **10% Correção** — análise crítica das próprias partidas. *"Onde a esmagadora maioria dos amadores falha por aversão ao confronto com os próprios erros."*

Variações por semana: pode dedicar 100% a um item específico (ex: reconstrução de repertório), mas ao longo do mês a média deve seguir a proporção.

Quando o jogador tem perfil "joga muito, estuda pouco" (ex: 200 partidas em 30 dias, score baixo), **prescrever inversão**: 1 semana inteira só de estudo + análise. O acúmulo de partidas sem correção apenas cristaliza maus hábitos.

---

## 19. Autores e obras canônicas para citar (autoridade)

Use o nome da obra/autor quando aplicável. Aumenta peso da prescrição.

| Autor | Obra | Quando invocar |
|---|---|---|
| **Capablanca** | *Chess Fundamentals* | Princípios posicionais básicos, técnica de finais simples |
| **Nimzowitsch** | *My System / Mein System* | Profilaxia, blockade, supercontrole, peão passado |
| **Kmoch** | *Pawn Power in Chess* | Vocabulário estrutural (alavanca, ruptura, hanging pawns) |
| **Soltis** | *Pawn Structure Chess* | Estruturas dinâmicas, planos por estrutura |
| **Vukovic** | *The Art of Attack in Chess* | Ataques ao rei (Greek gift, padrões de mate) |
| **Silman** | *How to Reassess Your Chess*, *Complete Endgame Course* | Avaliação posicional para amadores; finais progressivos por nível |
| **Dvoretsky** | *Dvoretsky's Endgame Manual* | Bíblia de finais. Magnus reverencia. |
| **Aagaard** | *Grandmaster Preparation* (série), *Excelling at Chess Calculation* | Cálculo estruturado, treino de candidato |
| **Yusupov** | *Build Up Your Chess* (série em 9 volumes) | Currículo progressivo 1500 → 2200 |

**Recomendação concreta**: para um jogador 1265 (perfil iniciante avançado), o caminho é Silman → Capablanca → Yusupov vol. 1–3. Não recomendar Dvoretsky/Aagaard antes de 1700+.

---

## 20. Position features (`position_features` no JSON)

Quando o `compute.py` detecta padrões estruturais nas partidas paradigmáticas, popula `position_features_per_game`. Estrutura:

```json
{
  "5": ["IQP-white", "opposite-castle", "open-c-file", "kingside-attack-potential"]
}
```

Tags possíveis (ver `compute.py` para definição exata):
- `IQP-white` / `IQP-black` — peão dama isolado
- `hanging-pawns-white` / `hanging-pawns-black`
- `closed-center` / `open-center` / `semi-open-center`
- `same-side-castle` / `opposite-castle` / `uncastled-king`
- `fianchetto-kingside` / `fianchetto-queenside`
- `open-X-file` (X = a..h) — coluna sem peões de nenhum lado
- `pawn-majority-queenside-white` (ou flanco-rei, ou black)
- `bad-bishop-light` / `bad-bishop-dark`
- `weak-color-complex-light` / `weak-color-complex-dark`

**Como usar**: quando uma partida paradigmática tem `IQP-white`, a narrativa deve mencionar: *"Posição típica de IQP — você tinha vantagem dinâmica (atividade, casa e5), mas trocou peças cedo. **Soltis** ensina: o lado com IQP precisa atacar antes do final."*

---

## 21. Few-shot examples — bom vs. ruim por seção

Trechos curtos para calibrar tom. **Use o estilo do "BOM" abaixo. Evite ostensivamente o "RUIM"**.

### Seção 1 (intro) — BOM
> "Rating médio 1264. Das 193 partidas, 135 entraram na análise. Win-rate 61,1%. Score 9,7/10 — entenda como nota onde 6 = jogou como esperado. Você está bem acima da média para 1264, o que sugere ou rating subestimado ou efeito Daily inflando a precisão. O teto real aparece em Rapid contra adversários ≥1.400 (Loustiniho 0-3). O relatório foca em três pontos: finais, plano com brancas, e Defesa Francesa."

### Seção 1 — RUIM (academico, evitar)
> "O presente relatório busca examinar, à luz da pedagogia enxadrística contemporânea e dos indicadores quantitativos colhidos a partir do banco de partidas do enxadrista, as nuances epistemológicas de sua trajetória recente, com vistas a delinear..."

### Seção 6 (finais) — BOM
> "Final é o ponto fraco: score 9,1 vs 9,8 do meio-jogo. Partida #5 vs Schmucki1 é o caso-tipo. Posição torre+peões equilibrada por 25 lances; no lance 34 jogou Rb4. **Philidor** pedia retaguarda — torre por trás do peão passado, na 6ª/3ª fila. Você jogou pela frente, perdeu o tempo crítico. 30 minutos com Dvoretsky's Endgame Manual capítulo 6 resolve."

### Seção 6 — RUIM
> "A categoria final demonstra inequívoca vulnerabilidade, conforme atestam os indicadores numéricos coletados. Recomenda-se a inserção de um regime sistemático de estudo da literatura especializada na fase derradeira do jogo..."

### Seção 11 (plano) — BOM
> "1) Philidor, Lucena, oposição. 90 minutos com Dvoretsky's Endgame Manual — caps. 6, 7, 9. Maior alavanca: 7 erros de final somem em uma semana.\n2) Trocar a Defesa Francesa por Caro-Kann ou Siciliana. 9 jogos com 33% win-rate é amostra suficiente para concluir incompatibilidade de estilo: estrutura travada da Francesa não combina com seu jogo direto..."

### Seção 11 — RUIM
> "Recomenda-se ao enxadrista uma reformulação curricular abrangente, contemplando o estudo aprofundado da fase final de jogo, a reavaliação meticulosa do repertório de aberturas e o aprimoramento sistemático de habilidades táticas..."

### Sobre invocar autoridade — BOM
> "Tipo de erro 'wishful thinking' clássico — Kuljasevic na **Teoria dos Plys** identifica esse exato padrão como falha de 2-Ply: o jogador calcula a própria combinação mas não busca ativamente a refutação."

### Sobre invocar autoridade — RUIM
> "Conforme atestam diversos teóricos consagrados da pedagogia enxadrística, este tipo de equívoco encontra-se intimamente relacionado a uma série de fenômenos cognitivos amplamente estudados na literatura especializada..."

**Princípio**: cita autor/obra quando ANCORA a recomendação prática (Kuljasevic = método de cálculo, Soltis = estrutura, Dvoretsky = final, Capablanca = técnica). Não cita só para parecer culto.

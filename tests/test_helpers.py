"""Testes das funções puras de compute.py (sem dependência de CSV)."""
import math
import pytest
from compute import (
    compute_score10,
    compute_accuracy,
    compute_confidence_pct,
    expected_acpl,
    depth_factor,
    classify_loss,
    phase_of_ply,
    cp_from_row,
)


# ── Score 10 ─────────────────────────────────────────────────────────────────

class TestScore10:
    def test_baseline_around_6_when_jogou_como_esperado(self):
        # ratio = 1.0 (jogou exatamente o esperado para o rating)
        # → score = 10*exp(-0.5) ≈ 6.07
        rating = 1500
        exp = expected_acpl(rating)
        df = depth_factor(20)
        # ACPL observado = expected (exatamente como esperado)
        score = compute_score10(exp * df, depth=20, rating=rating)
        assert 5.5 <= score <= 6.5

    def test_score_quando_joga_2x_melhor_que_esperado(self):
        rating = 1500
        exp = expected_acpl(rating)
        # Joga metade do ACPL esperado (2x melhor)
        score = compute_score10(exp * depth_factor(20) * 0.5, depth=20, rating=rating)
        assert 7.5 <= score <= 8.0

    def test_score_quando_joga_2x_pior_que_esperado(self):
        rating = 1500
        exp = expected_acpl(rating)
        score = compute_score10(exp * depth_factor(20) * 2.0, depth=20, rating=rating)
        assert 3.5 <= score <= 4.0

    def test_score_perfeito_acpl_zero(self):
        assert compute_score10(0, depth=15, rating=1200) == 10.0

    def test_score_acpl_negativo_vira_zero(self):
        assert compute_score10(-5, depth=15, rating=1200) == 0.0

    def test_score_none(self):
        assert compute_score10(None) == 0.0

    def test_depth_baixo_aumenta_score_para_mesmo_acpl(self):
        # ACPL idêntico em depth 10 vs depth 20: depth 10 reflete análise rasa,
        # então o ACPL_d20_eq é maior → score deveria cair ou subir?
        # ACPL_d20 = ACPL_obs / depth_factor (depth_factor menor em d10).
        # Então mesmo ACPL observado em d10 vira ACPL_d20 maior → score MENOR.
        s_d10 = compute_score10(20, depth=10, rating=1500)
        s_d20 = compute_score10(20, depth=20, rating=1500)
        assert s_d20 > s_d10  # mesmo ACPL, depth maior → score maior

    def test_rating_alto_torna_mesmo_acpl_pior(self):
        # Mesmo ACPL: GM (rating alto) ganha score muito menor que iniciante.
        s_gm = compute_score10(50, depth=20, rating=2500)
        s_amador = compute_score10(50, depth=20, rating=800)
        assert s_amador > s_gm


# ── Expected ACPL ────────────────────────────────────────────────────────────

class TestExpectedAcpl:
    @pytest.mark.parametrize("rating,lo,hi", [
        (800, 60, 75),
        (1200, 40, 55),
        (1600, 28, 40),
        (2000, 20, 30),
        (2400, 13, 22),
    ])
    def test_faixas_realistas(self, rating, lo, hi):
        v = expected_acpl(rating)
        assert lo <= v <= hi, f"rating {rating}: esperado entre {lo}-{hi}, foi {v}"

    def test_rating_invalido_usa_padrao(self):
        # Fórmula `max(8, 130 * exp(-1200/1200))` ≈ 47.8 (rating None vira 1200)
        assert 40 <= expected_acpl(None) <= 55
        assert 40 <= expected_acpl(0) <= 55

    def test_satura_em_8(self):
        # Mesmo rating absurdamente alto não pode ir abaixo de 8 cp esperado
        assert expected_acpl(5000) >= 8


# ── Depth factor ─────────────────────────────────────────────────────────────

class TestDepthFactor:
    def test_anchors(self):
        assert depth_factor(10) == pytest.approx(0.50, abs=0.01)
        assert depth_factor(20) == pytest.approx(1.00, abs=0.01)
        assert depth_factor(25) == pytest.approx(1.15, abs=0.01)

    def test_interpolacao_monotona(self):
        for d in range(10, 26):
            assert depth_factor(d) <= depth_factor(d + 1)

    def test_depth_menor_que_floor_clipa(self):
        assert depth_factor(5) == 0.50
        assert depth_factor(8) == 0.50

    def test_depth_maior_que_ceil_clipa(self):
        assert depth_factor(40) == 1.15

    def test_none_retorna_neutro(self):
        assert depth_factor(None) == 1.0


# ── Confidence ───────────────────────────────────────────────────────────────

class TestConfidence:
    def test_amostra_pequena_baixa_confianca(self):
        assert compute_confidence_pct(5, depth=15, eco_coverage=100) < 60

    def test_amostra_grande_satura(self):
        # n_games >> 50, depth alto, ECO 100% → confidence próximo 100
        assert compute_confidence_pct(200, depth=20, eco_coverage=100) >= 95

    def test_eco_zero_corta_20pct(self):
        com_eco = compute_confidence_pct(50, depth=18, eco_coverage=100)
        sem_eco = compute_confidence_pct(50, depth=18, eco_coverage=0)
        assert com_eco - sem_eco == pytest.approx(20, abs=2)

    def test_depth_zero(self):
        assert compute_confidence_pct(50, depth=0, eco_coverage=100) < compute_confidence_pct(50, depth=18, eco_coverage=100)


# ── Classify loss ────────────────────────────────────────────────────────────

class TestClassifyLoss:
    @pytest.mark.parametrize("cp,cat", [
        (0, "good"),
        (49, "good"),
        (50, "inaccuracy"),
        (99, "inaccuracy"),
        (100, "mistake"),
        (299, "mistake"),
        (300, "blunder"),
        (1000, "blunder"),
    ])
    def test_thresholds(self, cp, cat):
        assert classify_loss(cp) == cat


# ── Phase of ply ─────────────────────────────────────────────────────────────

class TestPhaseOfPly:
    def test_abertura_ate_ply_20(self):
        assert phase_of_ply(1, 60) == "abertura"
        assert phase_of_ply(20, 60) == "abertura"
        assert phase_of_ply(21, 60) == "meio-jogo"

    def test_final_ultimos_20_plies(self):
        assert phase_of_ply(40, 60) == "final"
        assert phase_of_ply(60, 60) == "final"

    def test_meio_jogo(self):
        assert phase_of_ply(30, 80) == "meio-jogo"

    def test_partida_curta_sem_meio_jogo(self):
        # Se total < 40 plies, abertura e final podem se sobrepor; final tem precedência
        assert phase_of_ply(25, 30) == "final"


# ── cp_from_row ──────────────────────────────────────────────────────────────

class TestCpFromRow:
    def test_evaluation_em_peoes_vira_centipeoes(self):
        # 0.5 peão = 50 cp
        assert cp_from_row({"evaluation": "0.5", "mate": ""}) == 50.0
        assert cp_from_row({"evaluation": "-1.2", "mate": ""}) == -120.0

    def test_mate_positivo_satura(self):
        # MATE_CAP_PAWNS = 10 (= 1000 cp)
        v = cp_from_row({"mate": 3, "evaluation": ""})
        assert v == 1000.0

    def test_mate_negativo_satura(self):
        v = cp_from_row({"mate": -5, "evaluation": ""})
        assert v == -1000.0

    def test_evaluation_invalido(self):
        assert cp_from_row({"evaluation": "xyz", "mate": ""}) == 0.0

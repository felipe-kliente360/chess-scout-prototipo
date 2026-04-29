"""Testes do módulo history.py (SQLite, in-memory)."""
import pytest
from history import (
    open_db, record_analysis, fetch_history, fetch_player, list_players,
    cache_position, get_cached_position, fen_to_key, cache_stats,
)


def make_computed(username="alice", stamp="20260101T100000", win_rate=50.0, score=6.0):
    return {
        "username": username,
        "stamp": stamp,
        "generated_at": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T10:00:00",
        "sample_quality": {
            "n_games_collected": 100, "n_games_relevant": 80, "confidence_pct": 90,
        },
        "kpis": {
            "win_rate": win_rate, "score_10": score, "acpl": 25.0,
            "blunders": 5, "mistakes": 10, "inaccuracies": 20,
        },
        "score_calibration": {
            "player_rating": 1500, "depth": 18, "performance_ratio": 1.0,
        },
    }


@pytest.fixture
def db(tmp_path):
    return open_db(tmp_path / "test.db")


class TestRecordAnalysis:
    def test_insere_player_e_analysis(self, db):
        record_analysis(db, make_computed())
        rows = fetch_history(db, "alice")
        assert len(rows) == 1
        assert rows[0]["score_10"] == 6.0
        p = fetch_player(db, "alice")
        assert p["total_cycles"] == 1

    def test_multiplos_ciclos_acumulam(self, db):
        record_analysis(db, make_computed(stamp="20260101T100000", score=5.0))
        record_analysis(db, make_computed(stamp="20260201T100000", score=6.5))
        record_analysis(db, make_computed(stamp="20260301T100000", score=7.0))
        rows = fetch_history(db, "alice")
        assert len(rows) == 3
        assert [r["score_10"] for r in rows] == [5.0, 6.5, 7.0]
        assert fetch_player(db, "alice")["total_cycles"] == 3

    def test_idempotente_mesmo_stamp(self, db):
        record_analysis(db, make_computed(stamp="20260101T100000", score=5.0))
        record_analysis(db, make_computed(stamp="20260101T100000", score=8.0))
        rows = fetch_history(db, "alice")
        assert len(rows) == 1
        assert rows[0]["score_10"] == 8.0  # último valor vence

    def test_perspective_marker(self, db):
        record_analysis(db, make_computed(), perspective="myself")
        rows = fetch_history(db, "alice")
        assert rows[0]["perspective"] == "myself"

    def test_perspective_preservada_em_update_se_none(self, db):
        record_analysis(db, make_computed(), perspective="myself")
        record_analysis(db, make_computed(), perspective=None)
        rows = fetch_history(db, "alice")
        assert rows[0]["perspective"] == "myself"


class TestFetchHistory:
    def test_ordem_cronologica(self, db):
        for s in ["20260301T100000", "20260101T100000", "20260201T100000"]:
            record_analysis(db, make_computed(stamp=s))
        rows = fetch_history(db, "alice")
        assert [r["stamp"] for r in rows] == ["20260101T100000", "20260201T100000", "20260301T100000"]

    def test_limit_pega_mais_recentes(self, db):
        for i in range(5):
            record_analysis(db, make_computed(stamp=f"2026010{i+1}T100000"))
        rows = fetch_history(db, "alice", limit=3)
        # limit=3 → 3 mais recentes, ordem cronológica
        assert [r["stamp"] for r in rows] == ["20260103T100000", "20260104T100000", "20260105T100000"]

    def test_username_inexistente(self, db):
        assert fetch_history(db, "ninguem") == []


class TestPositionCache:
    FEN_E4 = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
    FEN_E4_NO_EP = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"

    def test_fen_to_key_ignora_ep_e_contadores(self):
        # Mesma posição com/sem ep deve dar mesma chave
        k1 = fen_to_key(self.FEN_E4)
        k2 = fen_to_key(self.FEN_E4_NO_EP)
        assert k1 == k2
        assert "e3" not in k1  # ep stripped

    def test_cache_hit_basic(self, db):
        cache_position(db, self.FEN_E4, depth=18, best_move="c7c5", evaluation="0.20")
        hit = get_cached_position(db, self.FEN_E4, min_depth=15)
        assert hit is not None
        assert hit["best_move"] == "c7c5"
        assert hit["depth"] == 18

    def test_cache_miss_quando_depth_insuficiente(self, db):
        cache_position(db, self.FEN_E4, depth=10, best_move="c7c5")
        hit = get_cached_position(db, self.FEN_E4, min_depth=18)
        assert hit is None

    def test_cache_pega_maior_depth(self, db):
        cache_position(db, self.FEN_E4, depth=15, best_move="e7e5", evaluation="0.10")
        cache_position(db, self.FEN_E4, depth=20, best_move="c7c5", evaluation="0.20")
        cache_position(db, self.FEN_E4, depth=12, best_move="d7d5", evaluation="0.05")
        hit = get_cached_position(db, self.FEN_E4, min_depth=12)
        assert hit["depth"] == 20
        assert hit["best_move"] == "c7c5"

    def test_cache_idempotente(self, db):
        cache_position(db, self.FEN_E4, depth=15, best_move="e7e5")
        cache_position(db, self.FEN_E4, depth=15, best_move="c7c5")  # update
        db.commit()
        stats = cache_stats(db)
        assert stats["n"] == 1
        hit = get_cached_position(db, self.FEN_E4, min_depth=15)
        assert hit["best_move"] == "c7c5"  # último valor vence

    def test_cache_match_fen_diferente_em_ep(self, db):
        # Cacheia com EP, busca sem EP — deve hit (chave canônica)
        cache_position(db, self.FEN_E4, depth=18, best_move="c7c5")
        hit = get_cached_position(db, self.FEN_E4_NO_EP, min_depth=15)
        assert hit is not None
        assert hit["best_move"] == "c7c5"


class TestListPlayers:
    def test_multiplos_players(self, db):
        record_analysis(db, make_computed(username="alice"))
        record_analysis(db, make_computed(username="bob", stamp="20260102T100000"))
        players = list_players(db)
        assert {p["username"] for p in players} == {"alice", "bob"}

from datetime import date

from fof import ledger, run
from fof.model import player
from fof.store import db

OLD = "baseline-elo-context-v1"


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "PREDICTIONS", tmp_path / "predictions.jsonl")
    monkeypatch.setattr(ledger, "BETS", tmp_path / "bets.jsonl")
    con = db.connect(tmp_path / "fof.duckdb")
    db.upsert(con, "games", [dict(game_id=g, game_date=d, status=3, home_score=h, away_score=a)
                             for g, d, h, a in (("g1", date(2026, 11, 1), 110, 100), ("g2", date(2026, 11, 1), 90, 99),
                                                ("g3", date(2026, 11, 2), 101, 100))])
    pred = lambda gid, day, model, p: dict(id=f"{gid}:{model[-2:]}", game_id=gid, game_date=day, model=model,
                                           p_home=p, market_p_home=0.6, tip_utc=f"{day}T23:00:00+00:00")
    ledger.append(ledger.PREDICTIONS, [pred("g1", "2026-11-01", OLD, 0.7), pred("g2", "2026-11-01", OLD, 0.6),
                                       pred("g3", "2026-11-02", player.MODEL, 0.55)])
    ledger.append(ledger.BETS, [dict(id="g2:v1:bet", pred_id="g2:v1", game_id="g2", side="home", price=2.0),
                                dict(id="g3:v2:bet", pred_id="g3:v2", game_id="g3", side="home", price=1.9)])
    return con


def test_a_replaced_model_is_scored_apart(tmp_path, monkeypatch):
    card = run.scorecard(_setup(tmp_path, monkeypatch), date(2026, 11, 2))
    assert card["model"] == player.MODEL and card["since"] == "2026-11-02"
    assert card["all"]["n"] == 1 and card["bets"]["n"] == 1 and card["bets"]["profit"] > 0
    old = card["previous"][0]
    assert old["model"] == OLD and old["all"] == {"n": 2, "model_correct": 1, "market_n": 2, "market_correct": 1}
    assert old["bets"]["n"] == 1 and old["bets"]["profit"] == -1.0


def test_one_prediction_per_game_the_current_models(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    ledger.append(ledger.PREDICTIONS, [dict(id="g3:v1", game_id="g3", game_date="2026-11-02", model=OLD,
                                            p_home=0.4, tip_utc="2026-11-02T23:00:00+00:00")])
    rows = ledger.for_day(date(2026, 11, 2), player.MODEL)
    assert [r["id"] for r in rows] == ["g3:v2"]

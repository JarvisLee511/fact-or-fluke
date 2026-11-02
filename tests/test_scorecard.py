from datetime import date

from fof import digest, ledger, run
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


def test_the_email_shows_reasons_and_the_old_model_only_the_day_after_the_switch(tmp_path, monkeypatch):
    con = _setup(tmp_path, monkeypatch)
    p = dict(home="SAS", away="POR", p_home=0.8, tip_utc="2026-11-03T00:30:00+00:00", market_p_home=None,
             why={"players": 0.12, "absent": -0.031, "home": 0.04, "schedule": 0.001})
    assert digest.reasons(p) == "球員實力 SAS +12、主場 SAS +4、傷兵缺陣 POR +3"
    _, text, _ = digest.compose(date(2026, 11, 2), [p], run.scorecard(con, date(2026, 11, 2)), {}, 0, {}, False)
    assert "原因：球員實力 SAS +12" in text and "模型：球員影響力＋傷兵報告" in text
    assert "昨天（舊版模型：Elo＋賽程情境）：猜中 1/2" in text and "舊版模擬帳本（11/1）：-1.00u" in text
    _, text, _ = digest.compose(date(2026, 11, 3), [p], run.scorecard(con, date(2026, 11, 3)), {}, 0, {}, False)
    assert "昨天：模型猜中 1/1" in text and "舊版" not in text and "模擬帳本：11/2 起 +0.90u" in text


def test_one_prediction_per_game_the_current_models(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    ledger.append(ledger.PREDICTIONS, [dict(id="g3:v1", game_id="g3", game_date="2026-11-02", model=OLD,
                                            p_home=0.4, tip_utc="2026-11-02T23:00:00+00:00")])
    rows = ledger.for_day(date(2026, 11, 2), player.MODEL)
    assert [r["id"] for r in rows] == ["g3:v2"]

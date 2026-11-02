from datetime import date, datetime, timedelta, timezone

from fof import ledger, scores
from fof.model import player
from fof.store import db

TIP = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)       # 19:00 ET on 11/2


def _odds(taken, home_price, away_price, book="fanduel"):
    return [dict(taken_at=taken, event_id="e1", commence_utc=TIP.replace(tzinfo=None), home="BOS", away="MIA", book=book,
                 market="h2h", outcome=side, price=price, point=None)
            for side, price in (("BOS", home_price), ("MIA", away_price))]


def test_the_page_scores_the_model_its_bets_and_both_versions(tmp_path, monkeypatch):
    for name in ("PREDICTIONS", "BETS", "PREGAME"):
        monkeypatch.setattr(ledger, name, tmp_path / f"{name.lower()}.jsonl")
    con = db.connect(tmp_path / "fof.duckdb")
    db.upsert(con, "games", [dict(game_id="g1", game_date=date(2026, 11, 2), status=3, home_score=110, away_score=99)])
    db.upsert(con, "odds", _odds(TIP - timedelta(hours=10), 1.80, 2.10) + _odds(TIP - timedelta(minutes=20), 1.70, 2.25)
              + _odds(TIP - timedelta(minutes=40), 1.65, 2.20, book="lowvig"))       # not a Massachusetts book
    pred = dict(id="g1:v2", game_id="g1", game_date="2026-11-02", tip_utc=TIP.isoformat(), home="BOS", away="MIA",
                model=player.MODEL, p_home=0.62, market_p_home=0.54)
    ledger.append(ledger.PREDICTIONS, [pred])
    ledger.append(ledger.BETS, [dict(id="g1:v2:bet", pred_id="g1:v2", game_id="g1", side="home", price=1.80)])
    ledger.append(ledger.PREGAME, [dict(pred, id="g1:v2:pre:1800", p_home=0.70, made_at=(TIP - timedelta(hours=1)).isoformat()),
                                   dict(pred, id="g1:v2:pre:late", p_home=0.10, made_at=(TIP + timedelta(minutes=5)).isoformat())])
    card = {"model": player.MODEL, "label": "x", "since": "2026-11-02", "previous": []}
    page = scores.page(con, date(2026, 11, 3), card)
    assert page["model_all"]["n"] == 1 and page["model_all"]["correct"] == 1
    assert page["model_vs_market"]["market"]["n"] == 1
    assert page["calibration"] == [{"lo": 0.6, "hi": 0.7, "n": 1, "predicted": 0.62, "actual": 1.0}]
    led = page["ledger"]
    assert (led["n"], led["wins"]) == (1, 1) and abs(led["profit"] - 0.8) < 1e-9 and abs(led["profit_after_tax"] - 0.56) < 1e-9
    close_home = (1 / 1.70) / (1 / 1.70 + 1 / 2.25)          # the line 20 minutes before tip, not the morning's
    assert abs(page["clv"]["mean"] - (close_home * 1.80 - 1)) < 1e-9 and page["clv"]["beat"] == 1
    pre = page["versions"]["pregame"]
    assert pre["n"] == 1 and abs(pre["log_loss"] - 0.3566749) < 1e-6      # the 0.70 before tip; the late one ignored
    assert [b["book"] for b in page["books"]] == ["FanDuel"]

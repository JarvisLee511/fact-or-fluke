import json
from datetime import datetime, timedelta, timezone

from fof import betting, ledger, watch
from fof.config import ET

NOW = datetime(2026, 11, 2, 17, 0, tzinfo=ET)
TIP = (NOW + timedelta(hours=2)).isoformat()


def _team(code, star_rating, names):
    """A star (36 minutes when he plays, rating `star_rating`) and four others at 0, all playing lately."""
    players = {1 if code == "BOS" else 11: dict(min=36.0, k=0, cand=True, played=True, rating=star_rating,
                                                name=names[0], starter=True)}
    for i in range(2, 6):
        pid = i if code == "BOS" else 10 + i
        players[pid] = dict(min=30.0, k=0, cand=True, played=True, rating=0.0, name=f"{code} player {i}",
                            starter=i < 5)
    players[6 if code == "BOS" else 16] = dict(min=12.0, k=0, cand=True, played=True, rating=0.0,
                                               name=names[1], starter=False)
    keys = {v["name"].lower().replace(" ", ""): p for p, v in players.items()}
    return {"id": 100 if code == "BOS" else 200, "code": code, "listed": {}, "players": players, "names": keys}


def _table():
    return {"day": "2026-11-02", "model": "player-impact-v2", "version": "v2", "followed": ["BOS"],
            "weights": [0.0, 0.18, 0.28, 0.23, 0.04, 0.02, 0.081],
            "rates": {0: 0.9, 1: 0.5}, "report_rates": {"status": {"Out": 0.0, "Doubtful": 0.08, "Questionable": 0.5,
                                                                   "Probable": 0.85, "Available": 0.8},
                                                        "unlisted": {0: 0.89, 1: 0.5}},
            "games": [{"game_id": "g1", "tip_utc": TIP, "home": "BOS", "away": "MIA", "x": [0.5, 1.0, 0.0, 0.0, 0.0],
                       "p_home": None,
                       "teams": {"home": _team("BOS", 8.0, ["Star One", "Bench Guy"]),
                                 "away": _team("MIA", 2.0, ["Star Two", "Mia Bench"])}}]}


def _ready(table):
    g = table["games"][0]
    g["p_home"] = watch.win_prob(table, g, {s: g["teams"][s]["listed"] for s in ("home", "away")})[0]   # 0.709
    return table


def _report(*lines):
    return [dict(game_date="11/02/2026", matchup="MIA@BOS", team_tricode=team, player_name=name, status=st,
                 reason="Injury/Illness - Left Ankle; Sprain") for team, name, st in lines]


def _odds(bos, mia):
    """An Odds API answer: one book's moneyline for MIA@BOS."""
    start = datetime.fromisoformat(TIP).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return ([{"id": "e1", "home_team": "Boston Celtics", "away_team": "Miami Heat", "commence_time": start,
              "bookmakers": [{"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
                  {"name": "Boston Celtics", "price": bos}, {"name": "Miami Heat", "price": mia}]}]}]}],
            {"remaining": "400"})


def _repo(tmp_path, monkeypatch, bos, mia):
    """A private repo checkout: the morning table, its ledger row priced at bos/mia, the key, a fake mailbox."""
    t = _ready(_table())
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "2026-11-02.json").write_text(json.dumps(t), encoding="utf-8")
    p = t["games"][0]["p_home"]
    mv = {"best": {"BOS": [bos, "FanDuel"], "MIA": [mia, "DraftKings"]},
          "market_p_home": (1 / bos) / (1 / bos + 1 / mia)}
    ledger.append(tmp_path / "ledger" / "predictions.jsonl", [dict(
        id="g1:v2", game_id="g1", game_date="2026-11-02", model="player-impact-v2", home="BOS", away="MIA",
        tip_utc=TIP, p_home=p, market_p_home=mv["market_p_home"], odds_taken_at="2026-11-02T08:30:00-05:00",
        best=mv["best"], **betting.value(p, mv, "BOS", "MIA"))])
    sent = []
    monkeypatch.setattr(watch.email, "send", lambda *a: sent.append(a) or "id1")
    monkeypatch.setenv("ODDS_API_KEY", "k")
    return t, sent


def _feed(monkeypatch, reports, prices):
    """Successive reports [(lines, stamp)] and odds answers [(bos, mia) or None = refused], the last of each
    repeating. Returns the list the odds calls land in."""
    looks, calls = [], []

    def report(day):
        lines, stamp = reports[min(len(looks), len(reports) - 1)]
        looks.append(stamp)
        return _report(*lines), stamp

    def snapshot(*a, **k):
        answer = prices[min(len(calls), len(prices) - 1)]
        calls.append(answer)
        if answer is None:
            raise watch.FetchError("https://api.the-odds-api.com/v4", 429)
        return _odds(*answer)
    monkeypatch.setattr(watch, "_report", report)
    monkeypatch.setattr(watch.odds, "snapshot", snapshot)
    return calls


def _rows(tmp_path, name):
    path = tmp_path / "ledger" / name
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_star_ruled_out_is_recomputed_once():
    t = _ready(_table())
    st = watch.new_state(t)
    ups = watch.step(t, st, _report(("BOS", "Star One", "Out")), NOW)
    assert len(ups) == 1 and ups[0]["p"] < t["games"][0]["p_home"] - 0.05
    st["games"]["g1"]["listed"] = ups[0]["listed"]                  # what a run keeps once it acted
    assert watch.step(t, st, _report(("BOS", "Star One", "Out")), NOW) == []


def test_a_change_that_cannot_move_the_advice_costs_no_odds_call_and_sends_nothing(tmp_path, monkeypatch):
    _, sent = _repo(tmp_path, monkeypatch, 1.50, 3.00)             # the morning took BOS (+6.3%)
    calls = _feed(monkeypatch, [([("MIA", "Mia Bench", "Out")], "s1")], [(1.50, 3.00)])
    res = watch.run(tmp_path, NOW)
    assert res["updates"] == 1 and res["advice"] == [] and calls == [] and sent == []
    row = _rows(tmp_path, "pregame.jsonl")[0]
    assert row["advice_before"] == row["advice"] == "BOS" and not row["pushed"] and row["made_at"] < TIP


def test_a_morning_bet_no_longer_worth_it_is_called_off(tmp_path, monkeypatch):
    _, sent = _repo(tmp_path, monkeypatch, 1.50, 3.00)
    calls = _feed(monkeypatch, [([("BOS", "Star One", "Out")], "s1")], [(1.80, 2.10)])
    res = watch.run(tmp_path, NOW)
    assert res["advice"] == ["cancel BOS (MIA@BOS)"] and len(calls) == 1 and len(sent) == 1
    subject, text, html = sent[0]
    assert subject == "Fact or Fluke｜賽前更新 17:00｜取消 1 注"
    assert "取消　19:00  MIA @ BOS" in text and "早上推薦的 BOS 不值得投了：現在 1.80 @FanDuel，期望值 -1.2%" in text
    assert "原因：BOS 的 Star One 改成缺陣" in text and "<b>取消　19:00  MIA @ BOS</b>" in html
    assert _rows(tmp_path, "bets_pregame.jsonl") == []              # nothing new to bet on
    assert watch.run(tmp_path, NOW + timedelta(minutes=15))["updates"] == 0 and len(sent) == 1   # said once


def test_a_game_newly_worth_it_is_advised_and_booked_apart(tmp_path, monkeypatch):
    _, sent = _repo(tmp_path, monkeypatch, 1.40, 3.00)             # the morning had no bet (BOS -0.7%)
    calls = _feed(monkeypatch, [([("MIA", "Star Two", "Out")], "s1")], [(1.42, 3.10)])
    res = watch.run(tmp_path, NOW)
    assert res["advice"] == ["add BOS (MIA@BOS)"] and len(calls) == 1
    subject, text, _ = sent[0]
    assert subject == "Fact or Fluke｜賽前更新 17:00｜新增 1 注"
    assert "新增　19:00  MIA @ BOS" in text and "投 BOS：1.42 @FanDuel，期望值 +5.6%" in text
    assert "賠率低於 1.39 就不值得投" in text and "原因：MIA 的 Star Two 改成缺陣；模型 BOS 74%、賭盤 69%" in text
    bet = _rows(tmp_path, "bets_pregame.jsonl")
    assert [(b["team"], b["side"], b["price"], b["book"]) for b in bet] == [("BOS", "home", 1.42, "FanDuel")]
    assert bet[0]["made_at"] < TIP


def test_the_morning_side_back_in_favour_is_advised_again_but_not_booked_twice(tmp_path, monkeypatch):
    _, sent = _repo(tmp_path, monkeypatch, 1.50, 3.00)
    _feed(monkeypatch, [([("BOS", "Star One", "Out")], "s1"), ([("BOS", "Star One", "Available")], "s2")],
          [(1.80, 2.10), (1.50, 3.00)])
    assert watch.run(tmp_path, NOW)["advice"] == ["cancel BOS (MIA@BOS)"]
    assert watch.run(tmp_path, NOW + timedelta(minutes=15))["advice"] == ["add BOS (MIA@BOS)"]
    assert "新增　19:00  MIA @ BOS" in sent[1][1] and _rows(tmp_path, "bets_pregame.jsonl") == []


def test_when_the_odds_cannot_be_had_the_same_report_is_judged_again_next_time(tmp_path, monkeypatch):
    _, sent = _repo(tmp_path, monkeypatch, 1.50, 3.00)
    calls = _feed(monkeypatch, [([("BOS", "Star One", "Out")], "s1")], [None, (1.80, 2.10)])
    first = watch.run(tmp_path, NOW)
    assert first["waiting"] == ["g1"] and first["advice"] == [] and sent == []
    assert _rows(tmp_path, "pregame.jsonl") == []
    second = watch.run(tmp_path, NOW + timedelta(minutes=15))
    assert second["advice"] == ["cancel BOS (MIA@BOS)"] and len(calls) == 2 and len(sent) == 1


def test_a_state_saved_by_the_old_watch_is_filled_in(tmp_path, monkeypatch):
    t, _ = _repo(tmp_path, monkeypatch, 1.50, 3.00)
    old = {"stamp": "s0", "games": {"g1": {"listed": {"home": {}, "away": {}}, "p_sent": 0.7, "closed": True}}}
    path = tmp_path / "watch" / "2026-11-02.state.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    gs = watch.load_state(path, t, watch.morning_rows(tmp_path, t))["games"]["g1"]
    assert gs["p"] == 0.7 and gs["closed"] and gs["morning"] == gs["pick"] == "BOS"
    assert gs["view"]["best"]["BOS"][0] == 1.5


def test_closing_odds_are_due_only_shortly_before_tip():
    t = _ready(_table())
    st = watch.new_state(t)
    assert watch.due_closing(t, st, NOW) == []
    assert watch.due_closing(t, st, NOW + timedelta(minutes=100)) == ["g1"]
    assert watch.due_closing(t, st, NOW + timedelta(hours=2, minutes=1)) == []           # started
    st["games"]["g1"]["closed"] = True
    assert watch.due_closing(t, st, NOW + timedelta(minutes=100)) == []


def test_a_missing_table_is_reported_once_when_there_are_games(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "_report", lambda day: (_report(("BOS", "Star One", "Out")), "s"))
    sent = []
    monkeypatch.setattr(watch.email, "send", lambda *a: sent.append(a) or "id1")
    assert "alert" in watch.run(tmp_path, NOW) and sent[0][0] == "Fact or Fluke｜11/2 早上沒跑完"
    assert watch.run(tmp_path, NOW)["skip"].startswith("no table") and len(sent) == 1
    assert watch.run(tmp_path, NOW.replace(hour=15))["skip"] == "before 16:00 ET"


def test_an_unreadable_report_waits_for_the_next(tmp_path, monkeypatch):
    t = _ready(_table())
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "2026-11-02.json").write_text(json.dumps(t), encoding="utf-8")
    monkeypatch.setattr(watch.injury, "latest_stamps", lambda season: ["2026-11-02_04_30PM"])
    monkeypatch.setattr(watch.injury, "download", lambda stamp: b"not a pdf")
    res = watch.run(tmp_path, NOW, dry=True)
    assert res["report"].startswith("unavailable")


def test_a_game_the_sanity_check_held_back_calls_no_odds_at_each_small_change(tmp_path, monkeypatch):
    _, sent = _repo(tmp_path, monkeypatch, 1.80, 2.10)             # model 71% against the market's 54%: held back
    calls = _feed(monkeypatch, [([("MIA", "Mia Bench", "Out")], "s1")], [(1.80, 2.10)])
    assert watch.run(tmp_path, NOW)["advice"] == [] and calls == [] and sent == []

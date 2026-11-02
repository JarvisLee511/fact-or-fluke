import json
from datetime import datetime, timedelta

from fof import watch
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
    g["p_home"] = watch.win_prob(table, g, {s: g["teams"][s]["listed"] for s in ("home", "away")})[0]
    return table


def _report(*lines):
    return [dict(game_date="11/02/2026", matchup="MIA@BOS", team_tricode=team, player_name=name, status=st,
                 reason="Injury/Illness - Left Ankle; Sprain") for team, name, st in lines]


def test_a_star_ruled_out_moves_the_odds_and_is_pushed():
    t = _ready(_table())
    st = watch.new_state(t)
    ups = watch.step(t, st, _report(("BOS", "Star One", "Out")), NOW)
    assert len(ups) == 1 and ups[0]["moved"] and ups[0]["push"]
    assert ups[0]["p"] < t["games"][0]["p_home"] - 0.05
    assert watch.step(t, st, _report(("BOS", "Star One", "Out")), NOW) == []       # nothing new the next time


def test_small_changes_are_logged_but_only_a_followed_starter_who_may_now_sit_is_pushed():
    t = _ready(_table())
    bench = watch.step(t, watch.new_state(t), _report(("MIA", "Mia Bench", "Out")), NOW)
    assert len(bench) == 1 and not bench[0]["push"]                  # small move, not a followed team
    probable = watch.step(t, watch.new_state(t), _report(("BOS", "BOS player 2", "Probable")), NOW)
    assert not probable[0]["push"]                                   # still expected to play
    doubt = watch.step(t, watch.new_state(t), _report(("BOS", "BOS player 2", "Questionable")), NOW)
    assert doubt[0]["push"] and doubt[0]["starter"] and not doubt[0]["moved"]


def test_closing_odds_are_due_only_shortly_before_tip():
    t = _ready(_table())
    st = watch.new_state(t)
    assert watch.due_closing(t, st, NOW) == []
    assert watch.due_closing(t, st, NOW + timedelta(minutes=100)) == ["g1"]
    assert watch.due_closing(t, st, NOW + timedelta(hours=2, minutes=1)) == []           # started
    st["games"]["g1"]["closed"] = True
    assert watch.due_closing(t, st, NOW + timedelta(minutes=100)) == []


def test_the_email_names_the_player_and_the_new_odds():
    t = _ready(_table())
    ups = watch.step(t, watch.new_state(t), _report(("BOS", "Star One", "Out")), NOW)
    subject, text, html = watch.message([(u, watch.priced(u, None)) for u in ups], NOW)
    assert "賽前更新 17:00" in subject and "MIA@BOS" in subject
    assert "BOS：Star One 不在傷兵名單 → 缺陣" in text and "BOS 勝率" in text and "<div>" in html


def test_a_run_saves_its_state_and_log_and_does_not_repeat(tmp_path, monkeypatch):
    t = _ready(_table())
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "2026-11-02.json").write_text(json.dumps(t), encoding="utf-8")
    monkeypatch.setattr(watch, "_report", lambda day: (_report(("BOS", "Star One", "Out")), "2026-11-02_04_30PM"))
    sent = []
    monkeypatch.setattr(watch.email, "send", lambda *a: sent.append(a) or "id1")
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    first = watch.run(tmp_path, NOW)
    assert first["pushes"] == 1 and len(sent) == 1
    rows = [json.loads(line) for line in (tmp_path / "ledger" / "pregame.jsonl").read_text().splitlines()]
    assert rows[0]["pushed"] and rows[0]["changes"][0]["after"] == "Out" and rows[0]["made_at"] < TIP
    again = watch.run(tmp_path, NOW + timedelta(minutes=15))     # same report: nothing to say
    assert again["updates"] == 0 and len(sent) == 1


def test_a_missing_table_is_reported_once_when_there_are_games(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "_report", lambda day: (_report(("BOS", "Star One", "Out")), "s"))
    sent = []
    monkeypatch.setattr(watch.email, "send", lambda *a: sent.append(a) or "id1")
    assert "alert" in watch.run(tmp_path, NOW)
    assert watch.run(tmp_path, NOW)["skip"].startswith("no table") and len(sent) == 1
    assert watch.run(tmp_path, NOW.replace(hour=15))["skip"] == "before 16:00 ET"


def test_the_odds_api_failing_still_sends_the_numbers(tmp_path, monkeypatch):
    t = _ready(_table())
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "2026-11-02.json").write_text(json.dumps(t), encoding="utf-8")
    monkeypatch.setattr(watch, "_report", lambda day: (_report(("BOS", "Star One", "Out")), "s1"))
    sent = []
    monkeypatch.setattr(watch.email, "send", lambda *a: sent.append(a) or "id1")
    monkeypatch.setenv("ODDS_API_KEY", "k")

    def refused(*a, **k):
        raise watch.FetchError("https://api.the-odds-api.com/v4", 429)
    monkeypatch.setattr(watch.odds, "snapshot", refused)
    late = NOW + timedelta(minutes=100)                  # closing odds due too
    res = watch.run(tmp_path, late)
    assert res["pushes"] == 1 and len(sent) == 1 and "還沒有賠率" in sent[0][1]
    state = json.loads((tmp_path / "watch" / "2026-11-02.state.json").read_text())
    assert not state["games"]["g1"]["closed"]            # tried again next time


def test_an_unreadable_report_waits_for_the_next(tmp_path, monkeypatch):
    t = _ready(_table())
    (tmp_path / "watch").mkdir()
    (tmp_path / "watch" / "2026-11-02.json").write_text(json.dumps(t), encoding="utf-8")
    monkeypatch.setattr(watch.injury, "latest_stamps", lambda season: ["2026-11-02_04_30PM"])
    monkeypatch.setattr(watch.injury, "download", lambda stamp: b"not a pdf")
    res = watch.run(tmp_path, NOW, dry=True)
    assert res["report"].startswith("unavailable")

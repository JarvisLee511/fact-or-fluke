import json

from fof import betting, ledger


def test_value_flags_only_edges_of_three_percent_or_more():
    mv = {"best": {"SAS": (1.80, "FanDuel"), "POR": (2.20, "BetMGM")}}
    v = betting.value(0.58, mv, "SAS", "POR")
    assert round(v["ev"]["SAS"], 3) == 0.044 and v["pick"] == "SAS"
    assert betting.value(0.55, mv, "SAS", "POR")["pick"] is None      # 0.55 * 1.80 - 1 = -1%


def test_big_disagreement_with_the_market_is_not_a_bet():
    mv = {"best": {"ORL": (3.15, "theScore Bet"), "BOS": (1.40, "BetMGM")}, "market_p_home": 0.313}
    v = betting.value(0.438, mv, "ORL", "BOS")      # EV +38% only because the model misses an injury
    assert v["pick"] is None and v["suspect"] == "ORL"
    mv["market_p_home"] = 0.40
    assert betting.value(0.438, mv, "ORL", "BOS")["pick"] == "ORL"


def test_settle_taxes_winnings_but_not_losses():
    assert betting.settle(2.0, True) == (1.0, 0.7)
    assert betting.settle(2.0, False) == (-1.0, -1.0)


def test_ledger_appends_each_id_once(tmp_path):
    p = tmp_path / "x.jsonl"
    assert ledger.append(p, [{"id": "a", "v": 1}, {"id": "b", "v": 2}]) == 2
    assert ledger.append(p, [{"id": "a", "v": 99}, {"id": "c", "v": 3}]) == 1
    assert [r["id"] for r in ledger.read(p)] == ["a", "b", "c"]
    assert json.loads(p.read_text().splitlines()[0])["v"] == 1           # never rewritten


def test_odds_rows_maps_team_names_to_codes():
    snap = {"taken_at": "2026-11-01T01:09:09-05:00", "games": [{
        "id": "e1", "commence_time": "2026-11-01T20:40:00Z", "home_team": "Orlando Magic",
        "away_team": "Boston Celtics", "bookmakers": [{"key": "fanduel", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Orlando Magic", "price": 3.1}, {"name": "Boston Celtics", "price": 1.38}]}]}]}]}
    rows = betting.odds_rows(snap)
    assert {(r["home"], r["away"], r["outcome"], r["price"]) for r in rows} == {
        ("ORL", "BOS", "ORL", 3.1), ("ORL", "BOS", "BOS", 1.38)}

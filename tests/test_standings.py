from datetime import date, timedelta

import duckdb
import pytest

from fof.facts import standings

D1 = date(2026, 11, 1)


def fact(key, family, z, listed=False, observing=False, fluke=False, k=60, n=100, p0=0.4, luck=0.5, **detail):
    rate = k / n
    return dict(key=key, family=family, season="2026-27", subject_id=1, subject="Test Player", team="BOS",
                k=k, n=n, p0=p0, rate=rate, p_hat=rate, z=z, listed_now=listed, observing_now=observing,
                fluke_now=fluke, luck=luck, scanned=100, detail={"touch": "elbow", **detail})


@pytest.fixture
def run(monkeypatch):
    con = duckdb.connect(":memory:")

    def go(day, cands):
        monkeypatch.setattr(standings.families, "candidates", lambda con, season: [])
        monkeypatch.setattr(standings, "evaluate", lambda _: cands)
        return standings.update(con, "2026-27", day)

    def status():
        return {k: (s, r) for k, s, r in con.execute("select key, status, rank from facts").fetchall()}
    go.con = con
    return go, status


def test_ranks_cover_every_listed_fact_by_strength(run):
    go, status = run
    go(D1, [fact("a", "cs_share", 5.0, listed=True), fact("b", "cs_share", 7.0, listed=True),
            fact("c", "cs_share", 1.0, observing=True)])
    assert status() == {"a": ("listed", 2), "b": ("listed", 1), "c": ("observing", 1)}


def test_listed_facts_take_turns_by_kind(run):
    go, status = run
    go(D1, [fact("s1", "cs_share", 9.0, listed=True), fact("s2", "cs_share", 8.0, listed=True),
            fact("s3", "pullup_3p", 7.0, listed=True), fact("p1", "ast_partner", 5.0, listed=True, receiver="R")])
    # cs_share and pullup_3p are both shot style: style's 1st, partners' 1st, then style's 2nd and 3rd
    assert {k: r for k, (_, r) in status().items()} == {"s1": 1, "p1": 2, "s2": 3, "s3": 4}


def test_a_fluke_gets_its_verdict_and_goes_when_the_gap_does(run):
    go, status = run
    go(D1, [fact("h", "home_3p", 1.0, fluke=True, luck=3.2)])
    assert status() == {"h": ("fluke", 1)}
    assert go.con.execute("select verdict_zh from facts").fetchone()[0] == \
        "光靠運氣，每 31 人就會有 1 人差這麼多，這次掃過 100 人"       # 3.2 expected among 100
    go(D1 + timedelta(days=1), [fact("h", "home_3p", 0.2)])
    assert status() == {}


def test_a_split_gap_that_luck_explains_is_a_fluke_elsewhere_it_is_watched():
    # 49 players with no home/away gap and one 15-point gap on 60 threes: across 50, luck explains it
    cands = [dict(family="home_3p", key=f"k{i}", k=21, n=60, p0=0.35, n0=60, detail={}) for i in range(49)]
    cands.append(dict(family="home_3p", key="lucky", k=30, n=60, p0=0.35, n0=60, detail={}))
    out = {c["key"]: c for c in standings.evaluate(cands)}
    assert out["lucky"]["fluke_now"] and not out["lucky"]["listed_now"] and out["lucky"]["luck"] >= 1
    same = {c["key"]: c for c in standings.evaluate([dict(c, family="cs_share") for c in cands])}
    assert same["lucky"]["observing_now"] and not same["lucky"]["fluke_now"]      # not a split: keep watching


def test_a_one_way_family_has_no_story_the_other_way():
    cands = [dict(family="ast_partner", key=f"k{i}", k=5, n=200, p0=0.3, n0=2000, detail={}) for i in range(10)]
    cands.append(dict(family="ast_partner", key="up", k=120, n=200, p0=0.3, n0=2000, detail={}))
    out = {c["key"]: c for c in standings.evaluate(cands)}
    assert out["up"]["listed_now"]
    assert not any(c["listed_now"] or c["observing_now"] or c["fluke_now"] for k, c in out.items() if k != "up")


def test_observing_fact_that_falls_back_is_dropped(run):
    go, status = run
    go(D1, [fact("c", "cs_share", 1.0, observing=True)])
    go(D1 + timedelta(days=1), [fact("c", "cs_share", 0.2)])
    assert status() == {}


def test_listed_fact_missing_from_the_scan_gets_the_grace_then_goes(run):
    go, status = run
    go(D1, [fact("a", "cs_share", 5.0, listed=True), fact("b", "cs_share", 4.0, listed=True)])
    go(D1 + timedelta(days=1), [fact("b", "cs_share", 6.0, listed=True)])   # a keeps its last numbers
    assert status()["a"] == ("listed", 2)
    out = go(D1 + timedelta(days=15), [fact("b", "cs_share", 4.0, listed=True)])
    assert status()["a"] == ("eliminated", None) and out["eliminated"] == 1


def test_switching_to_the_other_view_of_a_fact_is_not_a_flip(run):
    go, status = run
    go(D1, [fact("t", "touch_shoot:elbow", 5.0, listed=True, k=60)])                 # shoots more
    out = go(D1 + timedelta(days=1), [fact("t", "touch_pass:elbow", -5.0, k=20)])  # passes less: same story
    assert status()["t"] == ("listed", 1) and out["eliminated"] == 0 and out["new_listed"] == 0


def test_direction_flip_within_one_view_eliminates_at_once(run):
    go, status = run
    go(D1, [fact("a", "cs_share", 5.0, listed=True, k=60)])
    out = go(D1 + timedelta(days=1), [fact("a", "cs_share", -1.0, k=30)])
    assert status()["a"] == ("eliminated", None) and out["eliminated"] == 1

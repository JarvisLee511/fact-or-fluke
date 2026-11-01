from datetime import date, timedelta

import duckdb
import pytest

from fof.facts import standings

D1 = date(2026, 11, 1)


def fact(key, family, z, listed=False, observing=False, k=60, n=100, p0=0.4, **detail):
    rate = k / n
    return dict(key=key, family=family, season="2026-27", subject_id=1, subject="Test Player", team="BOS",
                k=k, n=n, p0=p0, rate=rate, p_hat=rate, z=z, listed_now=listed, observing_now=observing,
                detail={"pos": "G", "touch": "elbow", **detail})


@pytest.fixture
def run(monkeypatch):
    con = duckdb.connect(":memory:")

    def go(day, cands):
        monkeypatch.setattr(standings.families, "candidates", lambda con, season: [])
        monkeypatch.setattr(standings, "evaluate", lambda _: cands)
        return standings.update(con, "2026-27", day)

    def status():
        return {k: (s, r) for k, s, r in con.execute("select key, status, rank from facts").fetchall()}
    return go, status


def test_ranks_cover_every_listed_fact_by_strength(run):
    go, status = run
    go(D1, [fact("a", "cs_share", 5.0, listed=True), fact("b", "cs_share", 7.0, listed=True),
            fact("c", "cs_share", 1.0, observing=True)])
    assert status() == {"a": ("listed", 2), "b": ("listed", 1), "c": ("observing", None)}


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

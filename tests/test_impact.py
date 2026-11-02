from datetime import date, timedelta

import numpy as np

from fof.model import impact
from fof.store import db

HOME, AWAY = 1, 2
GOOD, BAD = 101, 106        # two home players, one who adds points and one who costs them; the others are
                            # average (a player who never changes teams is only rated against his teammates)


def _db(tmp_path, days=40, seed=0):
    rng = np.random.default_rng(seed)
    con = db.connect(tmp_path / "fof.duckdb")
    games, stints, checks = [], [], []
    for g in range(days):
        gid, day = f"g{g}", date(2024, 11, 1) + timedelta(days=g)
        games.append(dict(game_id=gid, season="2024-25", season_type="Regular Season", game_date=day, home_id=HOME,
                          away_id=AWAY, status=3, neutral=False))
        checks.append(dict(game_id=gid, ok=True))
        for k in range(30):
            home = list(rng.choice(range(100, 108), 5, replace=False))
            away = list(rng.choice(range(200, 208), 5, replace=False))
            edge = 20.0 * ((GOOD in home) - (BAD in home))      # points per 100, big enough to beat the noise
            poss = 4.0
            hp = max(0, round(rng.normal(poss * (1.12 + edge / 200), 2.0)))
            ap = max(0, round(rng.normal(poss * (1.12 - edge / 200), 2.0)))
            stints.append(dict(game_id=gid, idx=k, period=1, start_s=0, end_s=1, home_pts=hp, away_pts=ap,
                               home_poss=poss, away_poss=poss,
                               **{f"h{i + 1}": int(p) for i, p in enumerate(home)},
                               **{f"a{i + 1}": int(p) for i, p in enumerate(away)}))
    db.upsert(con, "games", games)
    db.upsert(con, "stints", stints)
    db.upsert(con, "stint_checks", checks)
    return con


def test_ratings_find_the_good_and_the_bad_player(tmp_path):
    con = _db(tmp_path)
    seasons, players, order = impact.load(con)
    r = impact.Walk(seasons, players, order, lam=200.0).ratings("2024-25", date(2025, 1, 1))
    net = {p: r.o[p] + r.d[p] for p in r.o if p < 200}
    assert max(net, key=lambda p: net[p]) == GOOD and min(net, key=lambda p: net[p]) == BAD
    assert 100 < r.mu["2024-25"] < 125


def test_a_rating_uses_only_games_before_its_day(tmp_path):
    con = _db(tmp_path, days=10)
    seasons, players, order = impact.load(con)
    walk = impact.Walk(seasons, players, order, lam=200.0)
    first = walk.ratings("2024-25", date(2024, 11, 1))        # nothing played yet: no ratings at all
    assert not first.o
    a, _ = impact.normal(seasons["2024-25"], date(2024, 11, 3))
    b, _ = impact.normal(seasons["2024-25"])
    assert a.sum() < b.sum()

"""Walk-forward backtest of the Phase 2 player model against the Elo baseline and the betting market.

Every game day from 2017-18 on, player ratings are refitted from the games before that day (impact.Walk);
each team's rating is its players' impact weighted by expected minutes, under each state of knowledge in
fof.model.minutes; win probabilities come from logistic models fitted only on earlier seasons. The market
line (odds_history, internal only) is compared on the games that have one.

    python scripts/backtest.py [--every 7] [--lam 4000] [--decay 0.7] [--no-box]

Writes data/backtest/rows.pkl (one row per game, local only) and prints the season-by-season table.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
import pandas as pd

from fof.config import DATA
from fof.model import baseline, impact, minutes, player
from fof.store import db

MODES = ["morning", "report", "active", "lineup", "oracle"]
CALIBRATE = {"2020-21"}     # the first full season of readable injury reports: how often each status plays
FIRST = "2017-18"            # 2016-17 is the first season of stints: it only seeds the ratings
CONTEXT = ["home", "b2b", "rest", "tif"]


def calibration(con, tg: list[tuple], first: str) -> tuple[dict, dict, dict]:
    """The play rates behind the expected minutes (by run of missed games, counted over the first season),
    every past game's morning report statuses, and how often each status played (over CALIBRATE)."""
    rates = minutes.play_rates(tg, {first})
    status = minutes.report_status(con)
    return rates, status, minutes.play_rates_with_report(tg, status, CALIBRATE)


def rows(con, every: int, lam: float, decay: float, box: bool = True) -> pd.DataFrame:
    seasons, players, order = impact.load(con)
    walk = impact.Walk(seasons, players, order, lam=lam, decay=decay, box=impact.load_box(con) if box else None)
    tg = minutes.team_games(con)
    rates, status, report_rates = calibration(con, tg, order[0])
    exp = minutes.expected(tg, rates, status, report_rates)
    cols = ["game_id", "season", "game_date", "tip_utc", "home_id", "away_id", "home_code", "away_code",
            "home_score", "away_score", "neutral", "status"]
    games = [dict(zip(cols, r)) for r in con.execute(
        f"select {', '.join(cols)} from games where tip_utc is not null order by tip_utc").fetchall()]
    feats = {r["game_id"]: r for r in baseline.feature_rows(games)}
    market = dict(con.execute("""
        select game_id, (case when ml_home > 0 then 100 / (ml_home + 100) else -ml_home / (100 - ml_home) end) /
               ((case when ml_home > 0 then 100 / (ml_home + 100) else -ml_home / (100 - ml_home) end) +
                (case when ml_away > 0 then 100 / (ml_away + 100) else -ml_away / (100 - ml_away) end))
        from odds_history""").fetchall())
    todo = con.execute("""select game_id, season, game_date, home_id, away_id, home_score > away_score
                          from games where status = 3 and season >= ? and season_type in
                          ('Regular Season', 'Playoffs', 'PlayIn') order by game_date, tip_utc""",
                       [FIRST]).fetchall()
    out, r, last = [], None, None
    for gid, season, day, home, away, won in todo:
        if r is None or season != last[0] or (day - last[1]).days >= every:
            r, last = walk.ratings(season, day), (season, day)
        f = feats.get(gid)
        if f is None:
            continue
        row = dict(game_id=gid, season=season, game_date=day, y=float(won), market=market.get(gid),
                   **dict(zip(baseline.FEATURES, f["x"])), hca=r.home.get(season, 0.0),
                   has_report=(gid, home) in status and (gid, away) in status)
        for mode in MODES:
            h, a = exp[mode].get((gid, home)), exp[mode].get((gid, away))
            row[mode] = player.team_strength(r, h) - player.team_strength(r, a) if h and a else np.nan
        out.append(row)
    return pd.DataFrame(out)


def walk_forward(df: pd.DataFrame, features: list[str]) -> np.ndarray:
    """Each season's probabilities from a logistic model fitted on the seasons before it (NaN for the first)."""
    p = np.full(len(df), np.nan)
    ok = df[features].notna().all(axis=1).to_numpy()
    for season in sorted(df.season.unique())[1:]:
        train = ((df.season < season).to_numpy()) & ok
        test = (df.season == season).to_numpy() & ok
        w = baseline.fit(df.loc[train, features].to_numpy(), df.loc[train, "y"].to_numpy())
        p[test] = baseline.predict(w, df.loc[test, features].to_numpy())
    return p


def ll(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=7, help="refit the ratings every N days")
    ap.add_argument("--lam", type=float, default=impact.LAM)
    ap.add_argument("--decay", type=float, default=impact.DECAY)
    ap.add_argument("--no-box", dest="box", action="store_false", help="priors of 0 instead of box score lines")
    args = ap.parse_args(argv)
    t0 = time.time()
    con = db.connect(read_only=True)
    df = rows(con, args.every, args.lam, args.decay, args.box)
    con.close()
    (DATA / "backtest").mkdir(parents=True, exist_ok=True)
    df.to_pickle(DATA / "backtest" / "rows.pkl")
    models = {"elo": baseline.FEATURES, **{m: [m] + CONTEXT for m in MODES},
              **{f"elo+{m}": baseline.FEATURES + [m] for m in MODES}}
    for name, feats in models.items():
        df[f"p_{name}"] = walk_forward(df, feats)
    ev = df[df.season > FIRST]
    print(f"{len(df)} games, {time.time() - t0:.0f}s (ratings every {args.every} days, lam {args.lam:g}, "
          f"decay {args.decay:g})\nlog loss by season (lower is better)")
    print(f"{'season':<9}{'n':>6}" + "".join(f"{k:>14}" for k in models) + f"{'market':>9}{'mkt n':>7}")
    for season, g in list(ev.groupby("season")) + [("all", ev)]:
        m = g.market.notna()
        line = f"{season:<9}{len(g):>6}" + "".join(f"{ll(g[f'p_{k}'], g.y):>14.4f}" for k in models)
        line += f"{ll(g.market[m], g.y[m]):>9.4f}{int(m.sum()):>7}" if m.any() else f"{'-':>9}{0:>7}"
        print(line)
    for label, sub in (("the games with a market line", ev[ev.market.notna()]),
                       ("the games with a morning injury report and a market line",
                        ev[ev.market.notna() & ev.has_report])):
        print(f"\non {label} ({len(sub)}):")
        for k in list(models) + ["market"]:
            col = sub["market"] if k == "market" else sub[f"p_{k}"]
            print(f"  {k:<14} log loss {ll(col, sub.y):.4f}  accuracy {((col > 0.5) == (sub.y == 1)).mean():.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

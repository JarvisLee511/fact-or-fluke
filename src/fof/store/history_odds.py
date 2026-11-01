"""Historical moneylines, only for comparing the model with the market in backtests.

Source: the odds database of github.com/kyleskom/NBA-Machine-Learning-Sports-Betting, pinned to one commit and
apparently scraped from Sportsbook Review. That repo states no license and does not say whether its lines are
openers or closers, so these numbers stay in the local archive and the internal backtest: they are never shown
on the site, put in the public repo or used for the paper ledger (which uses our own snapshots).
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import duckdb

from ..config import RAW
from ..ingest.injury import TEAM_TRICODE

COMMIT = "8e36b0b72ecc5082aa8976dff742cdf910b3aa36"
SOURCE = (f"https://raw.githubusercontent.com/kyleskom/NBA-Machine-Learning-Sports-Betting/{COMMIT}"
          "/Data/OddsData.sqlite")
PATH = RAW / "odds_history" / "OddsData.sqlite"


def _table(names: set[str], season: str, lite: sqlite3.Connection) -> str | None:
    """The clean table for a season: 'odds_<season>_new' or '<season>'; plain 'odds_<season>' only when its dates
    are real dates (the older ones hold mangled values like '2016-17-0101')."""
    for t in (f"odds_{season}_new", season):
        if t in names:
            return t
    t = f"odds_{season}"
    if t in names:
        first = lite.execute(f'select Date from "{t}" limit 1').fetchone()
        try:
            date.fromisoformat(first[0][:10])
            return t
        except (TypeError, ValueError):
            return None
    return None


def rows(con: duckdb.DuckDBPyConnection, path: Path = PATH) -> list[dict]:
    """Moneylines matched to our game ids by date (a day either way) and home / away team."""
    if not path.exists():
        return []
    games = {(d, h, a): (gid, s) for gid, s, d, h, a in con.execute(
        "select game_id, season, game_date, home_code, away_code from games").fetchall()}
    lite = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        names = {r[0] for r in lite.execute("select name from sqlite_master where type = 'table'")}
        seasons = sorted({n.removeprefix("odds_").removesuffix("_new") for n in names})
        out = []
        for season in seasons:
            table = _table(names, season, lite)
            if table is None:
                continue
            for d, home, away, ml_h, ml_a, spread, total in lite.execute(
                    f'select Date, Home, Away, ML_Home, ML_Away, Spread, OU from "{table}"'):
                h, a = TEAM_TRICODE.get(home), TEAM_TRICODE.get(away)
                try:
                    day = date.fromisoformat(str(d)[:10])
                except ValueError:
                    continue
                hit = next((games[k] for k in ((day + timedelta(days=x), h, a) for x in (0, -1, 1)) if k in games), None)
                if hit and ml_h and ml_a:
                    out.append(dict(game_id=hit[0], season=hit[1], ml_home=float(ml_h), ml_away=float(ml_a),
                                    spread=spread, total=total))
        return out
    finally:
        lite.close()

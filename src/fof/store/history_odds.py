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
OLD_NAMES = {"Charlotte Bobcats": "CHA"}    # the file keeps Charlotte's pre-2014 name through 2021-22


def _table(names: set[str], season: str, lite: sqlite3.Connection) -> str | None:
    """The fullest table for a season with real dates. A season has up to three: 'odds_<season>_new', '<season>'
    and 'odds_<season>'; the older 'odds_<season>' hold mangled dates like '2016-17-0101', and
    'odds_2023-24_new' lacks 60 of the 1,255 games in '2023-24'."""
    best, most = None, 0
    for t in (f"odds_{season}_new", season, f"odds_{season}"):
        if t not in names:
            continue
        first, n = lite.execute(f'select min(Date), count(*) from "{t}"').fetchone()
        try:
            date.fromisoformat(str(first)[:10])
        except ValueError:
            continue
        if n > most:
            best, most = t, n
    return best


def _num(v) -> float | None:
    """A number from the file's mixed cells: ints, floats, numeric strings, 'PK' (pick'em, a spread of 0) or 'NL'
    (no line)."""
    if isinstance(v, str) and v.strip().upper() == "PK":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def rows(con: duckdb.DuckDBPyConnection, path: Path = PATH) -> list[dict]:
    """Moneylines matched to our game ids by date and home / away team. A line dated a day off goes to the game
    a day either way only if no line has that game on its own date: a playoff series plays every other day.
    Lines for postponed games (the January 2025 Los Angeles fires) match nothing, rightly: the game was played
    weeks later at another price."""
    if not path.exists():
        return []
    games = {(d, h, a): (gid, s) for gid, s, d, h, a in con.execute(
        "select game_id, season, game_date, home_code, away_code from games").fetchall()}
    lite = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        names = {r[0] for r in lite.execute("select name from sqlite_master where type = 'table'")}
        seasons = sorted({n.removeprefix("odds_").removesuffix("_new") for n in names})
        out: dict[str, dict] = {}
        off_by_a_day = []
        for season in seasons:
            table = _table(names, season, lite)
            if table is None:
                continue
            for d, home, away, ml_h, ml_a, spread, total in lite.execute(
                    f'select Date, Home, Away, ML_Home, ML_Away, Spread, OU from "{table}"'):
                h, a = (TEAM_TRICODE.get(t) or OLD_NAMES.get(t) for t in (home, away))
                ml_h, ml_a = _num(ml_h), _num(ml_a)
                try:
                    day = date.fromisoformat(str(d)[:10])
                except ValueError:
                    continue
                if not (h and a and ml_h and ml_a):
                    continue
                line = dict(ml_home=ml_h, ml_away=ml_a, spread=_num(spread), total=_num(total))
                if (day, h, a) in games:
                    gid, s = games[day, h, a]
                    out[gid] = dict(game_id=gid, season=s, **line)
                else:
                    off_by_a_day.append((day, h, a, line))
        for day, h, a, line in off_by_a_day:
            hit = next((games[k] for k in ((day + timedelta(days=x), h, a) for x in (-1, 1))
                        if k in games and games[k][0] not in out), None)
            if hit:
                out[hit[0]] = dict(game_id=hit[0], season=hit[1], **line)
        return list(out.values())
    finally:
        lite.close()

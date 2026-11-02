"""Win model v2: Elo and schedule context plus the players expected to play tonight.

A team's strength is its players' impact (fof.model.impact: points per 100 possessions above average, refitted
every morning from all games so far) weighted by their expected minutes (fof.model.minutes, report mode: who
has been playing, today's rosters from the league's player index, the latest injury report). A logistic model
on the baseline's five features plus home strength minus away strength gives the home win probability. Its
weights, and the play rates behind the minutes, come from the walk-forward backtest (scripts/backtest.py);
scripts/fit_player_model.py refits them once a season into player_v2.json next to this file.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np

from ..config import previous_season
from . import baseline, impact, minutes

MODEL = "player-impact-v2"
VERSION = "v2"
PARAMS = Path(__file__).with_name("player_v2.json")
FEATURES = baseline.FEATURES + ["report"]


def team_strength(r: impact.Ratings, mins: dict[int, float]) -> float:
    """Expected points per 100 possessions above average while the team's players are on the floor."""
    return sum(m / 48.0 * (r.o.get(p, r.new_o) + r.d.get(p, r.new_d)) for p, m in mins.items())


def load_params(path: Path = PARAMS) -> dict:
    p = json.loads(path.read_text(encoding="utf-8"))
    p["rates"] = {int(k): v for k, v in p["rates"].items()}
    p["report_rates"]["unlisted"] = {int(k): v for k, v in p["report_rates"]["unlisted"].items()}
    return p


def rosters(con: duckdb.DuckDBPyConnection) -> dict[int, set[int]]:
    """{team_id: players on its roster today}, from the latest player index."""
    out: dict[int, set[int]] = {}
    for tid, pid in con.execute("select team_id, player_id from players where on_roster").fetchall():
        out.setdefault(tid, set()).add(pid)
    return out


def _p(w: np.ndarray, x: list[float]) -> float:
    return float(baseline.predict(w, np.array([x]))[0])


def predict(con: duckdb.DuckDBPyConnection, day: date, games: list[dict], now: datetime,
            params: dict | None = None, use_rosters: bool = True) -> dict[str, dict]:
    """`games`: baseline.feature_rows rows for games on `day` not played yet. {game_id: home win probability,
    features, why (each part's share: the probability with it minus without it), both teams' strength with
    the expected minutes and with every absent player back, and when the injury report used came out}.

    The parts: players (strength with everyone back), absent (what the absences cost), elo, home and
    schedule (back-to-backs, rest days, 3 games in 4 nights)."""
    if not games:
        return {}
    params = params or load_params()
    w = np.array(params["weights"])
    season = games[0]["season"]
    since = season
    for _ in range(impact.BACK):
        since = previous_season(since)
    seasons, players, order = impact.load(con, since)
    r = impact.Walk(seasons, players, order, box=impact.load_box(con, since)).ratings(season, day)
    t = minutes.Tracker()
    for _, _, tid, box in minutes.team_games(con, before=day):
        t.add(tid, box)
    teams = rosters(con) if use_rosters else {}
    listed, report_at = minutes.today_status(con, games, now, teams)
    out = {}
    for g in games:
        now_s, full_s = {}, {}
        for side in ("home", "away"):
            tid = g[f"{side}_id"]
            m = minutes.tonight(t, tid, params["rates"], params["report_rates"], teams.get(tid) or None,
                                listed.get((g["game_id"], tid)))
            now_s[side], full_s[side] = team_strength(r, m["report"]), team_strength(r, m["full"])
        x_now = now_s["home"] - now_s["away"]
        x_full = full_s["home"] - full_s["away"]
        x = list(g["x"]) + [x_now]
        p = _p(w, x)
        why = {"players": p - _p(w, x[:5] + [x_now - x_full]),
               "absent": p - _p(w, x[:5] + [x_full]),
               "elo": p - _p(w, [0.0] + x[1:]),
               "home": p - _p(w, x[:1] + [0.0] + x[2:]),
               "schedule": p - _p(w, x[:2] + [0.0, 0.0, 0.0] + x[5:])}
        out[g["game_id"]] = dict(p_home=p, features=dict(zip(FEATURES, x)), why=why,
                                 strength=[now_s["home"], now_s["away"]], healthy=[full_s["home"], full_s["away"]],
                                 report_at=report_at.get(g["game_id"]))
    return out

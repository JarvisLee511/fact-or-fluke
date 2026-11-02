"""Player impact: offensive and defensive points per 100 possessions against an average player, from lineup
stints (regularised adjusted plus-minus, RAPM).

Each stint gives one observation per side: that side's points per 100 possessions = the season's league
average + home court (home side, not at a neutral site) + the five attackers' O - the five defenders' D,
weighted by its possessions. Ridge regression pulls every rating toward a prior: 0 (an average player), or
the player's box score line (see Walk).
Earlier seasons count too, their possessions multiplied by `decay` per season back, so a rating starts
from the player's past and gives way to this season's games as they come. Only games whose stints pass
every check (stint_checks.ok) are used.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import duckdb
import numpy as np
import pandas as pd
import scipy.linalg as la
import scipy.sparse as sp

SIDE = 5
BOX = ["pts", "fg2a", "fg3a", "fta", "ast", "tov", "oreb", "dreb", "stl", "blk", "pf"]
PAD = 100.0                  # minutes of league-average play added to every player's box line
NEW_MPG = 12.0
LAM, DECAY, BACK = 4000.0, 0.7, 3   # ridge strength, per-season decay, seasons back: chosen on 2018-19 to 2020-21


@dataclass
class Season:
    season: str
    dates: np.ndarray        # game date of each observation (two per stint), sorted
    rows: sp.csr_matrix      # observations x columns
    y: np.ndarray            # points per 100 possessions
    w: np.ndarray            # possessions


@dataclass
class Ratings:
    o: dict[int, float]      # player id -> offensive impact
    d: dict[int, float]      # player id -> defensive impact (points per 100 kept off the board)
    mu: dict[str, float]     # season -> league points per 100
    home: dict[str, float]   # season -> home court, points per 100
    new_o: float = 0.0       # a player not seen yet
    new_d: float = 0.0


def load(con: duckdb.DuckDBPyConnection, since: str = "") -> tuple[dict[str, Season], list[int], list[str]]:
    """Every checked stint (of seasons from `since` on, if given) as observations. Columns: O for each player,
    D for each player, then a league average and a home-court term for each season."""
    cols = ", ".join([f"s.h{k}" for k in range(1, 6)] + [f"s.a{k}" for k in range(1, 6)])
    data = con.execute(f"""
        select g.season, g.game_date, coalesce(g.neutral, false) as neutral, {cols}, s.home_pts, s.away_pts,
               s.home_poss, s.away_poss
        from stints s join games g using (game_id) join stint_checks c using (game_id)
        where c.ok and g.season_type in ('Regular Season', 'Playoffs', 'PlayIn') and g.season >= ?
        order by g.game_date, s.game_id, s.idx""", [since]).fetchnumpy()
    seasons = sorted(set(data["season"].tolist()))
    lineup = np.column_stack([data[f"h{k}"] for k in range(1, 6)] + [data[f"a{k}"] for k in range(1, 6)])
    players = sorted(set(np.unique(lineup).tolist()))
    pidx = {p: i for i, p in enumerate(players)}
    n_p = len(players)
    n_cols = 2 * n_p + 2 * len(seasons)
    out = {}
    for si, season in enumerate(seasons):
        m = data["season"] == season
        lu = np.vectorize(pidx.get)(lineup[m])
        neutral = data["neutral"][m].astype(bool)
        dates = data["game_date"][m]
        obs_rows, obs_y, obs_w, obs_d = [], [], [], []
        for home_side in (True, False):
            att, dfn = (lu[:, :SIDE], lu[:, SIDE:]) if home_side else (lu[:, SIDE:], lu[:, :SIDE])
            pts = data["home_pts" if home_side else "away_pts"][m].astype(float)
            poss = data["home_poss" if home_side else "away_poss"][m].astype(float)
            keep = poss > 0
            n = int(keep.sum())
            r = np.repeat(np.arange(n), 2 * SIDE + 2)
            c = np.column_stack([att[keep], n_p + dfn[keep], np.full(n, 2 * n_p + si),
                                 np.full(n, 2 * n_p + len(seasons) + si)])
            v = np.column_stack([np.ones((n, SIDE)), -np.ones((n, SIDE)), np.ones(n),
                                 (home_side & ~neutral[keep]).astype(float)])
            obs_rows.append(sp.csr_matrix((v.ravel(), (r, c.ravel())), shape=(n, n_cols)))
            obs_y.append(100 * pts[keep] / poss[keep])
            obs_w.append(poss[keep])
            obs_d.append(dates[keep])
        d = np.concatenate(obs_d)
        order = np.argsort(d, kind="stable")
        out[season] = Season(season, d[order], sp.vstack(obs_rows).tocsr()[order], np.concatenate(obs_y)[order],
                             np.concatenate(obs_w)[order])
    return out, players, seasons


def normal(s: Season, before: date | None = None) -> tuple[sp.csr_matrix, np.ndarray]:
    """X'WX and X'Wy over a season's observations (those dated before `before`, if given)."""
    k = len(s.dates) if before is None else int(np.searchsorted(s.dates, np.datetime64(before), side="left"))
    x, w = s.rows[:k], s.w[:k]
    xw = x.multiply(w[:, None]).tocsr()
    return (x.T @ xw).tocsr(), np.asarray(xw.T @ s.y[:k]).ravel()


def load_box(con: duckdb.DuckDBPyConnection, since: str = "") -> pd.DataFrame:
    """Every player-game box score line that has minutes (of seasons from `since` on), with its season and
    date."""
    stats = ", ".join(f"pg.{c}" for c in BOX if c != "fg2a")
    return con.execute(f"""
        select g.season, g.game_date, pg.player_id, pg.seconds / 60.0 as minutes, pg.fga - pg.fg3a as fg2a, {stats}
        from player_games pg join games g using (game_id)
        where g.status = 3 and g.season_type in ('Regular Season', 'Playoffs', 'PlayIn') and pg.seconds > 0
          and g.season >= ?
        order by g.game_date""", [since]).df()


class Walk:
    """Ratings as of any day of a season, from that season's games so far plus `back` earlier seasons.

    With `box`, a player's prior is no longer 0 but his box score line (per 36 minutes over the same window,
    pulled toward the league's rates by PAD minutes, plus minutes per game) times weights found in the same
    solve, so the weights too come only from games before the day. A player not seen yet gets the prior of a
    league-average line in NEW_MPG minutes a game."""

    def __init__(self, seasons: dict[str, Season], players: list[int], order: list[str], lam: float = LAM,
                 decay: float = DECAY, back: int = BACK, box: pd.DataFrame | None = None):
        self.seasons, self.players, self.order = seasons, players, order
        self.lam, self.decay, self.back = lam, decay, back
        self.full = {s: normal(v) for s, v in seasons.items()}
        self.use_box = box is not None
        self.box: dict[str, pd.DataFrame] = {} if box is None else {str(s): g for s, g in box.groupby("season")}
        self.box_full = {s: _sums(g) for s, g in self.box.items()}

    def _order(self, season: str) -> list[str]:
        """The seasons up to `season`, which on its opening day has no games yet."""
        return self.order if season in self.order else self.order + [season]

    def _features(self, season: str, day: date, pids: list[int]) -> tuple[np.ndarray, np.ndarray]:
        """Standardised box features (rates per 36 minutes, minutes per game) for `pids`, and the same for a
        new player."""
        order = self._order(season)
        si = order.index(season)
        cur = self.box.get(season)
        tot = _sums(cur[cur["game_date"] < pd.Timestamp(day)]) if cur is not None else _sums(None)
        for k in range(1, self.back + 1):
            past = self.box_full.get(order[si - k]) if si - k >= 0 else None
            if past is not None:
                tot = tot.add(past * self.decay ** k, fill_value=0.0)
        tot = tot.reindex(pids).fillna(0.0)
        league = tot[BOX].sum() / tot["minutes"].sum()
        rates = (tot[BOX] + PAD * league).div(tot["minutes"] + PAD, axis=0) * 36.0
        mpg = (tot["minutes"] / tot["games"].where(tot["games"] > 0)).fillna(0.0)
        x = np.column_stack([rates.to_numpy(), mpg.to_numpy()])
        w = tot["minutes"].to_numpy() + 1e-9
        mean = (x * w[:, None]).sum(0) / w.sum()
        std = np.sqrt(((x - mean) ** 2 * w[:, None]).sum(0) / w.sum()) + 1e-9
        new = np.append(league.to_numpy() * 36.0, NEW_MPG)
        return (x - mean) / std, (new - mean) / std

    def ratings(self, season: str, day: date) -> Ratings:
        order = self._order(season)
        si = order.index(season)
        if season in self.seasons:
            a, b = normal(self.seasons[season], day)
        else:
            n = 2 * len(self.players) + 2 * len(self.order)
            a, b = sp.csr_matrix((n, n)), np.zeros(n)
        for k in range(1, self.back + 1):
            if si - k >= 0:
                fa, fb = self.full[order[si - k]]
                a, b = a + self.decay ** k * fa, b + self.decay ** k * fb
        n_p = len(self.players)
        active = np.flatnonzero(a.diagonal() > 0)
        dense = a[active][:, active].toarray()
        is_player = active < 2 * n_p
        dense[np.diag_indices_from(dense)] += np.where(is_player, self.lam, 1e-6)
        rhs = b[active]
        new_o = new_d = 0.0
        if self.use_box:   # unknowns become [ratings, weights for O, weights for D]
            rows = np.flatnonzero(is_player)
            on_o = active[rows] < n_p
            pids = [self.players[c if c < n_p else c - n_p] for c in active[rows]]
            feats, new = self._features(season, day, pids)
            k = feats.shape[1]
            c = np.zeros((len(active), 2 * k))
            c[rows[on_o], :k] = feats[on_o]
            c[rows[~on_o], k:] = feats[~on_o]
            dense = np.block([[dense, -self.lam * c], [-self.lam * c.T, self.lam * c.T @ c + np.eye(2 * k)]])
            rhs = np.concatenate([rhs, np.zeros(2 * k)])
            sol = la.solve(dense, rhs, assume_a="pos")
            beta, gamma = sol[:len(active)], sol[len(active):]
            new_o, new_d = float(new @ gamma[:k]), float(new @ gamma[k:])
        else:
            beta = la.solve(dense, rhs, assume_a="pos")
        o, d, mu, home = {}, {}, {}, {}
        n_s = len(self.order)
        for col, val in zip(active.tolist(), beta.tolist()):
            if col < n_p:
                o[self.players[col]] = val
            elif col < 2 * n_p:
                d[self.players[col - n_p]] = val
            elif col < 2 * n_p + n_s:
                mu[self.order[col - 2 * n_p]] = val
            else:
                home[self.order[col - 2 * n_p - n_s]] = val
        return Ratings(o, d, mu, home, new_o, new_d)


def _sums(g: pd.DataFrame | None) -> pd.DataFrame:
    """Minutes, box totals and games per player."""
    if g is None or g.empty:
        return pd.DataFrame(columns=["minutes", *BOX, "games"], dtype=float)
    return g.groupby("player_id")[["minutes", *BOX]].sum().assign(games=g.groupby("player_id").size())

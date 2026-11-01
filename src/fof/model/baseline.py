"""Baseline win model: logistic regression on pre-game Elo difference plus schedule context.

Features (home minus away, so positive favours the home team):
  elo     (home Elo - away Elo) / 100
  home    1 unless the game is at a neutral site
  b2b     away is on the 2nd night of a back-to-back (+1), home is (-1)
  rest    home rest days - away rest days, each capped at 4
  tif     away is playing its 3rd game in 4 days (+1), home is (-1)
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

import numpy as np

from . import elo

FEATURES = ["elo", "home", "b2b", "rest", "tif"]
GAME_TYPES = ("002", "004", "005", "006")


def schedule_context(games: list[dict]) -> dict[str, dict]:
    """Rest, back-to-back and 3-in-4 flags for every game (completed or upcoming), from the schedule alone."""
    last: dict[int, date] = {}
    recent: dict[int, list[date]] = defaultdict(list)
    out: dict[str, dict] = {}
    for g in games:
        d = g["game_date"]
        f: dict = {}
        for side in ("home", "away"):
            tid = g[f"{side}_id"]
            prev = last.get(tid)
            rest = (d - prev).days if prev else 7
            f[f"{side}_rest"] = min(rest, 4)
            f[f"{side}_b2b"] = rest == 1
            f[f"{side}_3in4"] = sum(1 for x in recent[tid] if (d - x).days <= 3) >= 2
        out[g["game_id"]] = f
        for side in ("home", "away"):
            tid = g[f"{side}_id"]
            last[tid] = d
            recent[tid] = [x for x in recent[tid] if (d - x).days <= 3] + [d]
    return out


def feature_rows(games: list[dict]) -> list[dict]:
    """games sorted by tip time. Adds pre-game Elo and schedule context to each game."""
    games = [g for g in games if g["game_id"][:3] in GAME_TYPES and g["home_id"] and g["away_id"]]
    pre, _ = elo.run(games)
    ctx = schedule_context(games)
    rows = []
    for g in games:
        rh, ra = pre[g["game_id"]]
        c = ctx[g["game_id"]]
        rows.append({**g, **c, "elo_home": rh, "elo_away": ra,
                     "x": [(rh - ra) / 100.0, 0.0 if g["neutral"] else 1.0,
                           float(c["away_b2b"]) - float(c["home_b2b"]), float(c["home_rest"] - c["away_rest"]),
                           float(c["away_3in4"]) - float(c["home_3in4"])]})
    return rows


def fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 50) -> np.ndarray:
    """Logistic regression with an intercept, fitted by Newton's method with a small ridge penalty."""
    Xb = np.column_stack([np.ones(len(X)), X])
    w = np.zeros(Xb.shape[1])
    pen = np.full(Xb.shape[1], l2)
    pen[0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-Xb @ w))
        grad = Xb.T @ (p - y) + pen * w
        hess = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(pen)
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def predict(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(w[0] + X @ w[1:])))


def metrics(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {"n": int(len(y)), "accuracy": float(((p > 0.5) == (y == 1)).mean()),
            "log_loss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
            "brier": float(((p - y) ** 2).mean())}


def calibration(p: np.ndarray, y: np.ndarray, bins: int = 10) -> list[tuple[float, float, int]]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum():
            out.append((float(p[m].mean()), float(y[m].mean()), int(m.sum())))
    return out

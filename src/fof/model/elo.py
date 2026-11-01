"""FiveThirtyEight-style NBA Elo: K=20, margin-of-victory multiplier, 75% carry-over between seasons.
Home-court advantage here is only used inside the Elo update; the baseline model fits its own."""
from __future__ import annotations

K = 20.0
HFA = 100.0
MEAN = 1505.0
CARRY = 0.75


def expected(diff: float) -> float:
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


def mov_multiplier(mov: int, winner_diff: float) -> float:
    return ((abs(mov) + 3) ** 0.8) / (7.5 + 0.006 * winner_diff)


def run(games: list[dict]) -> tuple[dict[str, tuple[float, float]], dict[int, float]]:
    """games sorted by tip time, each with game_id, season, home_id, away_id, home_score, away_score, neutral, status.
    Returns ({game_id: (home elo, away elo) before tip}, {team id: rating after the last final game})."""
    ratings: dict[int, float] = {}
    season = None
    pre: dict[str, tuple[float, float]] = {}
    for g in games:
        if g["season"] != season:
            if season is not None:
                ratings = {t: CARRY * r + (1 - CARRY) * MEAN for t, r in ratings.items()}
            season = g["season"]
        h, a = g["home_id"], g["away_id"]
        rh, ra = ratings.get(h, MEAN), ratings.get(a, MEAN)
        pre[g["game_id"]] = (rh, ra)
        if g["status"] != 3 or g["home_score"] is None or g["away_score"] is None:
            continue
        diff = rh + (0.0 if g["neutral"] else HFA) - ra
        mov = g["home_score"] - g["away_score"]
        won = mov > 0
        delta = K * mov_multiplier(mov, diff if won else -diff) * ((1.0 if won else 0.0) - expected(diff))
        ratings[h], ratings[a] = rh + delta, ra - delta
    return pre, ratings

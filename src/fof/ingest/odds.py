"""The Odds API (the-odds-api.com): NBA moneyline and spread snapshots from US sportsbooks.

Cost on the free plan (500 credits/month) is markets x regions per call, so one call for
h2h + spreads in the "us" region costs 2 credits and returns every upcoming NBA game.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

from .http import request

ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"


def snapshot(api_key: str, regions: str = "us", markets: str = "h2h,spreads") -> tuple[list[dict], dict]:
    """Returns (games, quota) where quota has the credits used/remaining reported by the API."""
    qs = urlencode(dict(apiKey=api_key, regions=regions, markets=markets, oddsFormat="decimal", dateFormat="iso"))
    raw, headers = request(f"{ODDS_URL}?{qs}", retries=1)
    quota = {k: headers.get(f"x-requests-{k}") for k in ("used", "remaining", "last")}
    return json.loads(raw), quota

"""The Odds API (the-odds-api.com): NBA moneyline and spread snapshots from Massachusetts-legal books.

Cost on the free plan (500 credits/month) is markets x regions per call, and naming up to 10
bookmakers counts as one region, so h2h + spreads for the MA books costs 2 credits per call and
returns every upcoming NBA game. Caesars (williamhill_us) and Fanatics were not returned on
2026-11-01; they stay in the list so they are picked up if the API starts carrying them.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

from .http import request

ODDS_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds"
MA_BOOKS = "draftkings,fanduel,betmgm,williamhill_us,fanatics,espnbet,ballybet"
BOOK_TITLES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars",
               "fanatics": "Fanatics", "espnbet": "theScore Bet", "ballybet": "Bally Bet"}


def snapshot(api_key: str, bookmakers: str = MA_BOOKS, markets: str = "h2h,spreads",
             regions: str | None = None) -> tuple[list[dict], dict]:
    """Returns (games, quota); quota holds the credits used/remaining/last reported by the API."""
    params = dict(apiKey=api_key, markets=markets, oddsFormat="decimal", dateFormat="iso")
    params.update({"regions": regions} if regions else {"bookmakers": bookmakers})
    raw, headers = request(f"{ODDS_URL}?{urlencode(params)}", retries=1)
    quota = {k: headers.get(f"x-requests-{k}") for k in ("used", "remaining", "last")}
    return json.loads(raw), quota


def best_moneyline(game: dict) -> dict[str, tuple[float, str]]:
    """{team name: (best decimal price, book title)} across the books in one game."""
    best: dict[str, tuple[float, str]] = {}
    for book in game.get("bookmakers", []):
        for market in book.get("markets", []):
            if market["key"] != "h2h":
                continue
            for o in market["outcomes"]:
                if o["price"] > best.get(o["name"], (0.0, ""))[0]:
                    best[o["name"]] = (float(o["price"]), BOOK_TITLES.get(book["key"]) or str(book["title"]))
    return best

"""Predictions against the market: best price per side across the Massachusetts books, the market's
own (de-vigged) probability, expected value, and the paper bets that follow from them (D2, D3)."""
from __future__ import annotations

from datetime import datetime, timedelta

import duckdb

from .config import ET
from .ingest.injury import TEAM_TRICODE
from .ingest.odds import BOOK_TITLES

VALUE_EDGE = 0.03       # D3: flag a side only when expected value >= +3%
SANITY_GAP = 0.10       # a model that disagrees with the market by more than this usually lacks news
                        # (injuries, rest) the market already has: no flag, no paper bet
STAKE = 1.0             # D2: flat one unit per paper bet
TAX_ON_WINNINGS = 0.30  # non-resident withholding on winnings; losses are not deductible


def odds_rows(snapshot: dict) -> list[dict]:
    """A snapshot's prices as odds-table rows. Games already under way are left out: a snapshot taken after some
    tips (a late scheduled run) holds live odds for them, not a pre-game line."""
    taken = snapshot["taken_at"]
    rows = []
    for g in snapshot["games"]:
        if datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00")) <= datetime.fromisoformat(taken):
            continue
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                for o in m["outcomes"]:
                    rows.append(dict(taken_at=taken, event_id=g["id"], commence_utc=g["commence_time"].rstrip("Z"),
                                     home=TEAM_TRICODE.get(g["home_team"], g["home_team"]),
                                     away=TEAM_TRICODE.get(g["away_team"], g["away_team"]), book=b["key"],
                                     market=m["key"], outcome=TEAM_TRICODE.get(o["name"], o["name"]),
                                     price=float(o["price"]), point=o.get("point")))
    return rows


def market_view(con: duckdb.DuckDBPyConnection, home: str, away: str, game_date, as_of: datetime,
                fresh: timedelta | None = None) -> dict | None:
    """Latest moneylines taken at or before as_of for this matchup on this ET date; with `fresh`, none taken
    longer than that before as_of."""
    taken = con.execute("""
        select max(taken_at) from odds
        where home = ? and away = ? and market = 'h2h' and taken_at <= ?
          and cast(timezone('America/New_York', commence_utc::timestamptz) as date) = ?""",
                        [home, away, as_of, game_date]).fetchone()[0]
    if taken is None or (fresh is not None and as_of - taken > fresh):
        return None
    rows = con.execute("""select book, outcome, price from odds
                          where home = ? and away = ? and market = 'h2h' and taken_at = ?""",
                       [home, away, taken]).fetchall()
    books: dict[str, dict[str, float]] = {}
    for book, outcome, price in rows:
        books.setdefault(book, {})[outcome] = price
    fair = [1 / p[home] / (1 / p[home] + 1 / p[away]) for p in books.values() if home in p and away in p]
    best = {}
    for side in (home, away):
        price, book = max(((p[side], b) for b, p in books.items() if side in p), default=(None, None))
        best[side] = (price, BOOK_TITLES.get(book, book) if book else None)
    return {"taken_at": taken, "market_p_home": sum(fair) / len(fair) if fair else None, "best": best,
            "books": len(books)}


def view_from_snapshot(games: list[dict], home: str, away: str, tip_utc: datetime, taken_at: str) -> dict | None:
    """market_view from an Odds API response instead of the odds table (the cloud watch has no database): the
    game whose teams match and whose listed start is within 6 hours of the official tip."""
    for g in games:
        if (TEAM_TRICODE.get(g["home_team"]), TEAM_TRICODE.get(g["away_team"])) != (home, away):
            continue
        start = datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00"))
        if abs((start - tip_utc).total_seconds()) > 6 * 3600:
            continue
        books: dict[str, dict[str, float]] = {}
        for b in g.get("bookmakers", []):
            for m in b.get("markets", []):
                if m["key"] == "h2h":
                    books[b["key"]] = {TEAM_TRICODE.get(o["name"], o["name"]): float(o["price"]) for o in m["outcomes"]}
        fair = [1 / q[home] / (1 / q[home] + 1 / q[away]) for q in books.values() if home in q and away in q]
        best = {}
        for side in (home, away):
            price, book = max(((q[side], b) for b, q in books.items() if side in q), default=(None, None))
            best[side] = (price, BOOK_TITLES.get(book, book) if book else None)
        return {"taken_at": taken_at, "market_p_home": sum(fair) / len(fair) if fair else None, "best": best,
                "books": len(books)}
    return None


def value(p_home: float, mv: dict, home: str, away: str) -> dict:
    """Expected value per side at the best price; pick = the side worth a paper bet (or None).
    suspect = a side that clears the edge only because the model disagrees too much with the market."""
    ev = {}
    for side, p in ((home, p_home), (away, 1 - p_home)):
        price = mv["best"][side][0]
        ev[side] = p * price - 1 if price else None
    pick = max((s for s in ev if ev[s] is not None and ev[s] >= VALUE_EDGE), key=lambda s: ev[s], default=None)
    suspect = None
    mk = mv.get("market_p_home")
    if pick and mk is not None and abs(p_home - mk) > SANITY_GAP:
        pick, suspect = None, pick
    return {"ev": ev, "pick": pick, "suspect": suspect}


def settle(price: float, won: bool) -> tuple[float, float]:
    """(profit, profit after the 30% tax on winnings) for a one-unit paper bet."""
    if won:
        gain = STAKE * (price - 1)
        return gain, gain * (1 - TAX_ON_WINNINGS)
    return -STAKE, -STAKE


def now_et() -> datetime:
    return datetime.now(ET)

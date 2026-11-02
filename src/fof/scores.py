"""The Scorecard page (site/data/scorecard.json): the current model against the betting market.

- hit rate and log loss, the model's and the market's (its de-vigged morning line), on the same games
- calibration: games grouped by the favourite's probability, against how often favourites won
- the paper ledger (D2/D3) before and after the 30% tax, and closing line value: each paper bet's price
  against the last line before tip (fair probability at the close x price - 1; positive = better than close)
- morning version against pre-game version (ledger/pregame.jsonl), each against the market of its moment:
  the morning line, and the closing line
- each Massachusetts book's cut on the moneyline this season, smallest first
Earlier models keep their own record (the strip card's `previous`), never merged into this one.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

import duckdb

from . import betting, ledger
from .ingest.odds import BOOK_TITLES, MA_BOOKS

BINS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
CLOSE_WITHIN = timedelta(minutes=60)     # a "closing" line is the last one taken this close to tip


def _ll(p: float, won: bool) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return -math.log(p if won else 1 - p)


def _summary(rows: list[tuple[float, bool]]) -> dict:
    """{n, correct, log_loss, brier} for (home probability, home won) pairs."""
    if not rows:
        return {"n": 0}
    return {"n": len(rows), "correct": sum((p > 0.5) == won for p, won in rows),
            "log_loss": sum(_ll(p, won) for p, won in rows) / len(rows),
            "brier": sum((p - won) ** 2 for p, won in rows) / len(rows)}


def closing(con: duckdb.DuckDBPyConnection, pred: dict) -> dict | None:
    """The last moneylines taken within CLOSE_WITHIN before tip, or None (no snapshot that close)."""
    tip = datetime.fromisoformat(pred["tip_utc"])
    if tip.tzinfo is None:
        tip = tip.replace(tzinfo=timezone.utc)
    mv = betting.market_view(con, pred["home"], pred["away"], date.fromisoformat(pred["game_date"]), tip)
    if not mv or tip - mv["taken_at"] > CLOSE_WITHIN:
        return None
    return mv


def calibration(rows: list[tuple[float, bool]]) -> list[dict]:
    """Games grouped by the favourite's probability: how sure the model was, and how often favourites won."""
    fav = [(max(p, 1 - p), won == (p >= 0.5)) for p, won in rows]
    out = []
    for lo, hi in zip(BINS[:-1], BINS[1:]):
        inside = [(q, w) for q, w in fav if lo <= q < hi]
        if inside:
            out.append({"lo": lo, "hi": min(hi, 1.0), "n": len(inside), "predicted": sum(q for q, _ in inside) / len(inside),
                        "actual": sum(w for _, w in inside) / len(inside)})
    return out


def books(con: duckdb.DuckDBPyConnection, season_start: date) -> list[dict]:
    """Each Massachusetts book's average cut (overround) on the moneyline over this season's games, smallest
    first."""
    rows = con.execute("""
        select book, avg(1 / ph + 1 / pa - 1), count(distinct event_id) from (
            select taken_at, event_id, book, max(price) filter (where outcome = home) as ph,
                   max(price) filter (where outcome = away) as pa
            from odds where market = 'h2h' and commence_utc >= ? and list_contains(?, book) group by all)
        where ph > 1 and pa > 1 group by book order by 2""", [season_start, MA_BOOKS.split(",")]).fetchall()
    return [{"book": BOOK_TITLES.get(b, b), "vig": v, "games": n} for b, v, n in rows]


def page(con: duckdb.DuckDBPyConnection, day: date, card: dict) -> dict:
    """The page's numbers for the model of `card` (run.scorecard), from its ledgers and the games table."""
    model = card["model"]
    results = {gid: h > a for gid, h, a in con.execute(
        "select game_id, home_score, away_score from games where status = 3").fetchall()}
    morning = [p for p in ledger.read(ledger.PREDICTIONS) if p.get("model") == model and p["game_id"] in results]
    by_id = {p["id"]: p for p in morning}
    with_market = [p for p in morning if p.get("market_p_home") is not None]
    bets = [b for b in ledger.read(ledger.BETS) if b.get("pred_id") in by_id]
    settled = [betting.settle(b["price"], results[b["game_id"]] == (b["side"] == "home")) for b in bets]
    clv = []
    for b in bets:
        close = closing(con, by_id[b["pred_id"]])
        if close and close["market_p_home"] is not None:
            p_side = close["market_p_home"] if b["side"] == "home" else 1 - close["market_p_home"]
            clv.append(p_side * b["price"] - 1)
    pregame = {}
    for r in ledger.read(ledger.PREGAME):        # each game's last pre-game number before tip
        made = datetime.fromisoformat(r["made_at"])
        if r.get("model") == model and r["game_id"] in results and made < datetime.fromisoformat(r["tip_utc"]):
            if r["game_id"] not in pregame or made > datetime.fromisoformat(pregame[r["game_id"]]["made_at"]):
                pregame[r["game_id"]] = r
    pre_rows, pre_morning, pre_close = [], [], []
    for gid, r in pregame.items():
        won = results[gid]
        pre_rows.append((r["p_home"], won))
        m = next((p for p in morning if p["game_id"] == gid), None)
        if m:
            pre_morning.append((m["p_home"], won))
        close = closing(con, r)
        if close and close["market_p_home"] is not None:
            pre_close.append((close["market_p_home"], won))
    start = date(int(card["since"][:4]) - (1 if int(card["since"][5:7]) < 8 else 0), 8, 1)
    return {
        "model": model, "label": card["label"], "since": card["since"], "day": day.isoformat(),
        "model_all": _summary([(p["p_home"], results[p["game_id"]]) for p in morning]),
        "model_vs_market": {"model": _summary([(p["p_home"], results[p["game_id"]]) for p in with_market]),
                            "market": _summary([(p["market_p_home"], results[p["game_id"]]) for p in with_market])},
        "calibration": calibration([(p["p_home"], results[p["game_id"]]) for p in morning]),
        "ledger": {"n": len(bets), "wins": sum(s[0] > 0 for s in settled), "profit": sum(s[0] for s in settled),
                   "profit_after_tax": sum(s[1] for s in settled)},
        "clv": {"n": len(clv), "beat": sum(v > 0 for v in clv), "mean": sum(clv) / len(clv) if clv else None},
        "versions": {"pregame": _summary(pre_rows), "morning_same_games": _summary(pre_morning),
                     "closing_market": _summary(pre_close)},
        "books": books(con, start),
        "previous": card.get("previous", []),
    }

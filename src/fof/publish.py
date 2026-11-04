"""Site data: site/data/*.json, rewritten after each daily run. The repo is public, so only derived
outputs go here (predictions, fun facts, final scores), never raw API responses."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

from . import ledger, scores
from .config import ROOT, now_et
from .facts import text
from .ingest.injury import TEAM_TRICODE
from .model.player import MODEL

SITE_DATA = ROOT / "site" / "data"
FOLLOWED = ["POR", "WAS", "PHI", "BOS", "MIA", "MEM", "OKC", "SAS", "MIN", "GSW", "DAL"]
TEAM_NAME = {code: name for name, code in TEAM_TRICODE.items() if name != "Los Angeles Clippers"}
FACT_COLS = ["key", "family", "kind", "season", "subject", "team", "k", "n", "p0", "rate", "status", "rank",
             "listed_on", "eliminated_on", "text_zh", "text_en", "basis_zh", "basis_en", "verdict_zh", "verdict_en"]


def _write(name: str, obj) -> None:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    tmp = SITE_DATA / f"{name}.tmp"
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, SITE_DATA / name)


def _facts(con, season: str, status: str, order: str, limit: int | None = None, per: int = 0) -> list[dict]:
    """Every fact, or the first `limit` (flagged top=True: the unfiltered view) plus each team's and each kind's
    first `per`, so the team and kind filters still have something to show."""
    if not limit:
        sql = f"select {', '.join(FACT_COLS)}, true from facts where season = ? and status = ? order by {order}"
    else:
        sql = f"""select {', '.join(FACT_COLS)}, overall <= {limit} from (
                      select *, row_number() over (order by {order}) as overall,
                                row_number() over (partition by team order by {order}) as in_team,
                                row_number() over (partition by kind order by {order}) as in_kind
                      from facts where season = ? and status = ?)
                  where overall <= {limit} or in_team <= {per} or in_kind <= {per} order by {order}"""
    return [dict(zip(FACT_COLS + ["top"], r)) for r in con.execute(sql, [season, status]).fetchall()]


def standings(con, seasons: list[tuple[str, str]]) -> dict:
    out = []
    for season, label in seasons:
        counts = dict(con.execute("select status, count(*) from facts where season = ? group by status",
                                  [season]).fetchall())
        out.append({"season": season, "label": label,
                    "counts": {s: counts.get(s, 0) for s in ("listed", "observing", "fluke", "eliminated")},
                    "listed": _facts(con, season, "listed", "rank"),
                    "observing": _facts(con, season, "observing", "rank", 60, 10),
                    "fluke": _facts(con, season, "fluke", "rank", 60, 10),
                    "eliminated": _facts(con, season, "eliminated", "eliminated_on desc, key", 60, 10)})
    return {"seasons": out, "kinds": {k: list(v) for k, v in text.KIND.items()}}


def results(con, day: date) -> list[dict]:
    rows = con.execute("""select game_id, tip_utc, away_code, home_code, away_score, home_score, status
                          from games where game_date = ? and season_type in ('Regular Season', 'Playoffs', 'PlayIn',
                          'Cup Final') order by tip_utc""", [day]).fetchall()
    preds = {p["game_id"]: p for p in ledger.for_day(day, MODEL)}
    out = []
    for gid, tip, away, home, a, h, status in rows:
        p = preds.get(gid)
        g = {"game_id": gid, "tip_utc": f"{tip.isoformat()}Z" if tip else None, "away": away, "home": home,
             "away_score": a, "home_score": h, "final": status == 3}
        if p and status == 3:
            home_won = h > a
            g["model_right"] = (p["p_home"] > 0.5) == home_won
            if p.get("market_p_home") is not None:
                g["market_right"] = (p["market_p_home"] > 0.5) == home_won
        out.append(g)
    return out


def last_night(con, day: date, season: str) -> dict:
    """Last night's games, and the fun facts this morning's update put on the standings or overturned."""
    moved = {}
    for status, on, order in (("listed", "listed_on", "rank"), ("eliminated", "eliminated_on", "key")):
        moved[status] = [dict(zip(FACT_COLS, r)) for r in con.execute(
            f"select {', '.join(FACT_COLS)} from facts where season = ? and status = ? and {on} = ? order by {order}",
            [season, status, day]).fetchall()]
    return {"day": (day - timedelta(days=1)).isoformat(), **moved, "games": results(con, day - timedelta(days=1))}


def publish(con, day: date, season: str, card: dict, night: dict, partial: bool) -> None:
    _write("today.json", {"day": day.isoformat(), "games": ledger.for_day(day, card["model"]), "scorecard": card})
    _write("lastnight.json", night)
    _write("scorecard.json", scores.page(con, day, card))
    demo = "2025-26"
    _write("standings.json", standings(con, [(season, season), (demo, f"{demo} demo")] if season != demo
                                       else [(season, season)]))
    _write("meta.json", {"generated_at": now_et().isoformat(), "day": day.isoformat(), "season": season,
                         "partial": partial, "followed": FOLLOWED, "teams": TEAM_NAME,
                         "model": card["model"], "model_zh": card["label"],
                         "model_en": card.get("label_en", card["label"])})

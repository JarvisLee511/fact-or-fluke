"""The season-long fun fact standings: observing -> listed -> eliminated, plus Fluke verdicts.

listed      shrunk gap >= the family's delta AND a Benjamini-Hochberg discovery that day
observing   raw gap >= delta but the evidence is not there yet
fluke       a situation split (home vs away, clutch, ...) with a raw gap >= delta that luck alone would
            produce at least once among everyone scanned that day
eliminated  was listed, then below the bar for 14 straight days or the direction flipped (kept on record)
Observing and fluke facts that fall back under the delta are dropped. Each status takes turns by kind (every
kind's first, then every kind's second, ...) so one kind of fact cannot fill the page. Within a kind, listed
and observing facts go by |z|, the more data behind a fact the higher it sits; Fluke verdicts go by how real
they look (the fewest expected by luck first).
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import duckdb

from . import evidence, families, text

GRACE = timedelta(days=14)

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    key VARCHAR PRIMARY KEY, family VARCHAR, season VARCHAR, subject_id BIGINT, subject VARCHAR, team VARCHAR,
    k INTEGER, n INTEGER, p0 DOUBLE, rate DOUBLE, p_hat DOUBLE, z DOUBLE, status VARCHAR, rank INTEGER,
    first_seen DATE, listed_on DATE, eliminated_on DATE, below_since DATE, text_zh VARCHAR, text_en VARCHAR,
    basis_zh VARCHAR, basis_en VARCHAR, detail VARCHAR, updated_on DATE);
ALTER TABLE facts ADD COLUMN IF NOT EXISTS kind VARCHAR;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS luck DOUBLE;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS scanned INTEGER;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS verdict_zh VARCHAR;
ALTER TABLE facts ADD COLUMN IF NOT EXISTS verdict_en VARCHAR;
CREATE TABLE IF NOT EXISTS fact_history (
    day DATE, key VARCHAR, k INTEGER, n INTEGER, z DOUBLE, status VARCHAR, PRIMARY KEY (day, key));
"""


def evaluate(cands: list[dict]) -> list[dict]:
    """Adds rate, p_hat, z, m, scanned, luck, listed_now, observing_now and fluke_now; drops samples below each
    family's min_n and keeps only the strongest view of each key."""
    by_fam: dict[str, list[dict]] = {}
    for c in cands:
        by_fam.setdefault(c["family"], []).append(c)
    out = []
    for fam, cs in by_fam.items():
        cfg = families.config(fam)
        cs = [c for c in cs if c["n"] >= cfg["min_n"]]
        if not cs:
            continue
        m = evidence.prior_strength([c["k"] for c in cs], [c["n"] for c in cs], [c["p0"] for c in cs])
        for c in cs:
            c["rate"] = c["k"] / c["n"]
            c["p_hat"], _, c["z"] = evidence.score(c["k"], c["n"], c["p0"], m, c["n0"])
            c["m"], c["scanned"] = m, len(cs)
            # how many of the scanned would look this extreme if nothing but luck were at work
            c["luck"] = len(cs) * evidence.two_sided_p(evidence.raw_z(c["k"], c["n"], c["p0"], c["n0"]))
        found = evidence.bh([evidence.two_sided_p(c["z"]) for c in cs])
        for c, f in zip(cs, found):
            story = not cfg.get("one_way") or c["rate"] > c["p0"]
            gap = story and abs(c["rate"] - c["p0"]) >= cfg["delta"]
            c["listed_now"] = story and bool(f) and abs(c["p_hat"] - c["p0"]) >= cfg["delta"]
            c["fluke_now"] = bool(cfg.get("split")) and gap and not c["listed_now"] and c["luck"] >= 1
            c["observing_now"] = gap and not c["listed_now"] and not c["fluke_now"]
        out += cs
    best: dict[str, dict] = {}
    for c in out:
        if c["key"] not in best or abs(c["z"]) > abs(best[c["key"]]["z"]):
            best[c["key"]] = c
    return list(best.values())


def update(con: duckdb.DuckDBPyConnection, season: str, day: date, season_label: str | None = None) -> dict:
    """Recompute candidates for a season, advance every fact's status, persist, and report the changes."""
    con.execute(SCHEMA)
    label = season_label or season
    cands = evaluate(families.candidates(con, season))
    cols = ["status", "first_seen", "listed_on", "eliminated_on", "below_since", "p_hat", "p0", "family"]
    old = {r[0]: dict(zip(cols, r[1:])) for r in con.execute(
        f"select key, {', '.join(cols)} from facts where season = ?", [season]).fetchall()}
    changes = {"new_listed": [], "eliminated": []}
    rows = []
    for c in cands:
        prev = old.get(c["key"])
        status, first_seen = None, (prev or {}).get("first_seen") or day
        listed_on, eliminated_on, below_since = ((prev or {}).get(k) for k in ("listed_on", "eliminated_on",
                                                                               "below_since"))
        was_listed = prev is not None and prev["status"] == "listed"
        if c["listed_now"]:
            status, below_since, eliminated_on = "listed", None, None
            if not was_listed:
                listed_on = day
                changes["new_listed"].append(c["key"])
        elif was_listed:  # a direction only means something within one view (shooting more = passing less)
            flipped = (prev["family"] == c["family"]
                       and (c["p_hat"] - c["p0"]) * ((prev["p_hat"] or 0) - (prev["p0"] or 0)) < 0)
            below_since = below_since or day
            if flipped or day - below_since >= GRACE:
                status, eliminated_on = "eliminated", day
                changes["eliminated"].append(c["key"])
            else:
                status = "listed"
        elif prev is not None and prev["status"] == "eliminated":
            status = "eliminated"
        elif c["fluke_now"]:
            status = "fluke"
        elif c["observing_now"]:
            status = "observing"
        if status is None:
            continue
        zh, en = text.sentence(c)
        bzh, ben = text.basis(c, label)
        vzh, ven = text.verdict(c, status) if families.config(c["family"]).get("split") else (None, None)
        rows.append(dict(key=c["key"], family=c["family"], season=season, subject_id=c["subject_id"],
                         subject=c["subject"], team=c["team"], k=c["k"], n=c["n"], p0=c["p0"], rate=c["rate"],
                         p_hat=c["p_hat"], z=c["z"], status=status, rank=None, first_seen=first_seen,
                         listed_on=listed_on, eliminated_on=eliminated_on, below_since=below_since,
                         text_zh=zh, text_en=en, basis_zh=bzh, basis_en=ben, detail=json.dumps(c["detail"]),
                         updated_on=day, kind=families.config(c["family"])["kind"], luck=c["luck"],
                         scanned=c["scanned"], verdict_zh=vzh, verdict_en=ven))
    from ..store import db
    db.upsert(con, "facts", rows)
    db.upsert(con, "fact_history", [dict(day=day, key=r["key"], k=r["k"], n=r["n"], z=r["z"], status=r["status"])
                                    for r in rows])
    seen = {r["key"] for r in rows}
    for key, prev in old.items():
        if key in seen:
            continue
        if prev["status"] in ("observing", "fluke"):    # back under the delta: nothing left to tell
            con.execute("delete from facts where key = ?", [key])
        elif prev["status"] == "listed":     # out of today's scan: same grace as falling below the bar
            below_since = prev["below_since"] or day
            gone = day - below_since >= GRACE
            con.execute("update facts set status = ?, eliminated_on = ?, below_since = ?, updated_on = ? "
                        "where key = ?", ["eliminated" if gone else "listed", day if gone else None,
                                          below_since, day, key])
            if gone:
                changes["eliminated"].append(key)
    con.execute("update facts set rank = null where season = ?", [season])
    for status, strength in (("listed", "abs(z) desc"), ("observing", "abs(z) desc"), ("fluke", "luck")):
        con.execute(f"""update facts set rank = r.rk
                        from (select key, row_number() over (order by turn, {strength}, key) as rk
                              from (select key, z, luck,
                                           row_number() over (partition by kind order by {strength}, key) as turn
                                    from facts where season = ? and status = ?)) r
                        where facts.key = r.key""", [season, status])
    counts = dict(con.execute("select status, count(*) from facts where season = ? group by status",
                              [season]).fetchall())
    return {**{s: counts.get(s, 0) for s in ("listed", "observing", "fluke", "eliminated")},
            "candidates": len(cands), **{k: len(v) for k, v in changes.items()}}

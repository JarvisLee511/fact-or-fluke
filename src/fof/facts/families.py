"""Candidate 'pattern' fun facts, one builder per family (season-to-date, regular season).

Every candidate has: family, season, key, subject_id, subject, team, k, n, p0 (the comparison rate),
n0 (sample size behind p0, or None when p0 is a pooled peer rate with negligible noise) and detail for the
text. Two views of one thing (3P% and FG% off the same passer; shooting and passing out of the same touch)
share a key: only the stronger is kept each day, and the fact keeps its place in the standings when the
stronger view changes.
"""
from __future__ import annotations

import json
from collections import defaultdict

import duckdb

# delta: smallest gap from the comparison that is worth telling; min_n: smallest sample scanned
FAMILIES = {
    "pass_3p": dict(delta=0.06, min_n=15),
    "pass_fg": dict(delta=0.06, min_n=20),
    "touch_shoot": dict(delta=0.10, min_n=40),
    "touch_pass": dict(delta=0.10, min_n=40),
    "cs_share": dict(delta=0.10, min_n=40),
    "pullup_3p": dict(delta=0.06, min_n=30),
    "tight_fg": dict(delta=0.08, min_n=30),
    "corner_side": dict(delta=0.15, min_n=20),
    "corner_3p": dict(delta=0.07, min_n=25),
}
TOUCH = {  # measure, touches column, prefix of the FGA / passes columns
    "elbow": ("ElbowTouch", "ELBOW_TOUCHES", "ELBOW_TOUCH"),
    "post": ("PostTouch", "POST_TOUCHES", "POST_TOUCH"),
    "paint": ("PaintTouch", "PAINT_TOUCHES", "PAINT_TOUCH"),
    "drive": ("Drives", "DRIVES", "DRIVE"),
}


def base_family(family: str) -> str:
    return family.split(":")[0]


def _flip_name(last_first: str) -> str:
    last, _, first = last_first.partition(",")
    return f"{first.strip()} {last.strip()}".strip() if first else last_first


class Context:
    """Per-season lookups shared by the builders."""

    def __init__(self, con: duckdb.DuckDBPyConnection, season: str):
        self.con, self.season = con, season
        self.pos = {pid: (p or "?").split("-")[0][:1] or "?"
                    for pid, p in con.execute("select player_id, position from players").fetchall()}
        rows = con.execute("""
            select pg.player_id, any_value(pg.name), arg_max(pg.team_code, g.tip_utc), sum(pg.fg3a), sum(pg.fga)
            from player_games pg join games g using (game_id)
            where g.season = ? and g.season_type = 'Regular Season' group by pg.player_id""", [season]).fetchall()
        self.name = {r[0]: r[1] for r in rows}
        self.team = {r[0]: r[2] for r in rows}
        self.fg3a = {r[0]: r[3] for r in rows}

    def dash(self, measure: str) -> list[dict]:
        as_of = self.con.execute("select max(as_of) from dash where season = ? and measure = ?",
                                 [self.season, measure]).fetchone()[0]
        if as_of is None:
            return []
        return [json.loads(d) for (d,) in self.con.execute(
            "select data from dash where season = ? and measure = ? and as_of = ?",
            [self.season, measure, as_of]).fetchall()]

    def who(self, pid: int, fallback: str = "") -> tuple[str, str]:
        return self.name.get(pid, fallback), self.team.get(pid, "")


def _cand(family, ctx: Context, pid, k, n, p0, n0=None, group=None, other="", **detail) -> dict:
    name, team = ctx.who(pid, detail.pop("fallback_name", ""))
    key = "|".join([group or family, ctx.season, str(pid), str(other)])
    return dict(family=family, season=ctx.season, key=key, subject_id=pid, subject=name, team=team,
                k=int(k), n=int(n), p0=float(p0), n0=n0, detail=detail)


def pooled_by_position(rows: list[tuple[int, float, float]], pos: dict) -> dict[str, float]:
    k, n = defaultdict(float), defaultdict(float)
    for pid, ki, ni in rows:
        g = pos.get(pid, "?")
        k[g] += ki
        n[g] += ni
    return {g: k[g] / n[g] for g in n if n[g] > 0}


def passes(ctx: Context) -> list[dict]:
    # only players who played last night are re-fetched each morning, so take each player's newest snapshot
    rows = ctx.con.execute("""
        select player_id, passer_id, passer_name, fgm, fga, fg3m, fg3a from passes p
        where season = ? and as_of = (select max(as_of) from passes q
                                      where q.season = p.season and q.player_id = p.player_id)""",
                           [ctx.season]).fetchall()
    if not rows:
        return []
    tot = defaultdict(lambda: [0, 0, 0, 0])
    for pid, _, _, fgm, fga, fg3m, fg3a in rows:
        t = tot[pid]
        t[0] += fgm or 0; t[1] += fga or 0; t[2] += fg3m or 0; t[3] += fg3a or 0
    out = []
    for pid, passer_id, passer_name, fgm, fga, fg3m, fg3a in rows:
        for fam, k, n, K, N in (("pass_3p", fg3m, fg3a, tot[pid][2], tot[pid][3]),
                                ("pass_fg", fgm, fga, tot[pid][0], tot[pid][1])):
            k, n = k or 0, n or 0
            if n < 1 or N - n < 30:
                continue
            out.append(_cand(fam, ctx, pid, k, n, (K - k) / (N - n), n0=N - n, other=passer_id,
                             group="pass", passer=_flip_name(passer_name), k0=K - k))
    return out


def touches(ctx: Context) -> list[dict]:
    out = []
    for touch, (measure, tcol, pre) in TOUCH.items():
        rows = ctx.dash(measure)
        for action, col in (("shoot", f"{pre}_FGA"), ("pass", f"{pre}_PASSES")):
            data = [(r["PLAYER_ID"], r.get(col) or 0, r.get(tcol) or 0) for r in rows if r.get(tcol)]
            base = pooled_by_position(data, ctx.pos)
            for pid, k, n in data:
                g = ctx.pos.get(pid, "?")
                if g in base:
                    out.append(_cand(f"touch_{action}:{touch}", ctx, pid, k, n, base[g], other=touch,
                                     group="touch", touch=touch, pos=g,
                                     fallback_name=next(r["PLAYER_NAME"] for r in rows if r["PLAYER_ID"] == pid)))
    return out


def shooting_style(ctx: Context) -> list[dict]:
    cs = {r["PLAYER_ID"]: r for r in ctx.dash("CatchShoot")}
    pu = {r["PLAYER_ID"]: r for r in ctx.dash("PullUpShot")}
    out = []
    share = [(pid, r.get("CATCH_SHOOT_FG3A") or 0, ctx.fg3a.get(pid) or 0) for pid, r in cs.items()]
    share = [(pid, min(k, n), n) for pid, k, n in share if n]
    base = pooled_by_position(share, ctx.pos)
    for pid, k, n in share:
        g = ctx.pos.get(pid, "?")
        if g in base:
            out.append(_cand("cs_share", ctx, pid, k, n, base[g], pos=g, fallback_name=cs[pid]["PLAYER_NAME"]))
    for pid, r in pu.items():
        c = cs.get(pid)
        k, n = r.get("PULL_UP_FG3M") or 0, r.get("PULL_UP_FG3A") or 0
        if c and n and (c.get("CATCH_SHOOT_FG3A") or 0) >= 30:
            k0, n0 = c["CATCH_SHOOT_FG3M"], c["CATCH_SHOOT_FG3A"]
            out.append(_cand("pullup_3p", ctx, pid, k, n, k0 / n0, n0=n0, k0=int(k0), fallback_name=r["PLAYER_NAME"]))
    return out


def tight_defense(ctx: Context) -> list[dict]:
    rows = ctx.dash("CloseDef_0-2")
    data = [(r["PLAYER_ID"], r.get("FGM") or 0, r.get("FGA") or 0) for r in rows if r.get("FGA")]
    base = pooled_by_position(data, ctx.pos)
    names = {r["PLAYER_ID"]: r["PLAYER_NAME"] for r in rows}
    return [_cand("tight_fg", ctx, pid, k, n, base[ctx.pos.get(pid, "?")], pos=ctx.pos.get(pid, "?"),
                  fallback_name=names[pid]) for pid, k, n in data if ctx.pos.get(pid, "?") in base]


def corners(ctx: Context) -> list[dict]:
    rows = ctx.con.execute("""
        select player_id,
               sum((zone_basic = 'Left Corner 3')::int), sum((zone_basic in ('Left Corner 3', 'Right Corner 3'))::int),
               sum((zone_basic in ('Left Corner 3', 'Right Corner 3') and made)::int),
               sum((zone_basic = 'Above the Break 3')::int), sum((zone_basic = 'Above the Break 3' and made)::int)
        from shots where season = ? and season_type = 'Regular Season' group by player_id""", [ctx.season]).fetchall()
    left_total = sum(r[1] for r in rows)
    corner_total = sum(r[2] for r in rows)
    out = []
    for pid, left, corner, corner_made, atb, atb_made in rows:
        if corner and corner_total:
            out.append(_cand("corner_side", ctx, pid, left, corner, left_total / corner_total))
        if corner and atb >= 50:
            out.append(_cand("corner_3p", ctx, pid, corner_made, corner, atb_made / atb, n0=atb, k0=atb_made, atb=atb))
    return out


BUILDERS = [passes, touches, shooting_style, tight_defense, corners]


def candidates(con: duckdb.DuckDBPyConnection, season: str) -> list[dict]:
    ctx = Context(con, season)
    out: list[dict] = []
    for build in BUILDERS:
        out += build(ctx)
    return out

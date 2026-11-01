"""Candidate 'pattern' fun facts, one builder per family (season-to-date, regular season).

Every candidate has: family, season, key, subject_id, subject, team, k, n, p0 (the comparison rate),
n0 (sample size behind p0, or None when p0 is a pooled peer rate with negligible noise) and detail for the
text. Two views of one thing (3P% and FG% off the same passer; shooting and passing out of the same touch;
home 3P% and home FG%) share a key: only the stronger is kept each day, and the fact keeps its place in the
standings when the stronger view changes.

Role facts compare a player with the 30 players whose role is closest to his (shot volume, assists and
rebounds per 36 minutes, height) instead of his listed position, so "a ball-dominant star creates his own
threes" is not news. Situation splits (split=True) compare a player or a team with itself: home vs away,
clutch vs the rest, and so on. When such a gap is within what luck alone produces across everyone scanned,
the standings show it as a Fluke verdict.
"""
from __future__ import annotations

import json
from collections import defaultdict

import duckdb
import numpy as np

from ..config import previous_season

# delta: smallest gap from the comparison that is worth telling; min_n: smallest sample scanned; kind: the group
# the standings take turns between and filter by; split: a situation split; one_way: only "more than the
# comparison" is a story (the other way round mostly means two players are rarely on the floor together)
FAMILIES = {
    "pass_3p": dict(delta=0.06, min_n=15, kind="partner"),
    "pass_fg": dict(delta=0.06, min_n=20, kind="partner"),
    "ast_partner": dict(delta=0.08, min_n=100, kind="partner", one_way=True),
    "touch_shoot": dict(delta=0.10, min_n=40, kind="touch"),
    "touch_pass": dict(delta=0.10, min_n=40, kind="touch"),
    "cs_share": dict(delta=0.10, min_n=40, kind="style"),
    "pullup_3p": dict(delta=0.06, min_n=30, kind="style"),
    "tight_fg": dict(delta=0.08, min_n=30, kind="contest"),
    "corner_side": dict(delta=0.15, min_n=20, kind="corner"),
    "corner_3p": dict(delta=0.07, min_n=25, kind="corner"),
    "zone_fg": dict(delta=0.06, min_n=50, kind="zone"),
    "clutch_usage": dict(delta=0.06, min_n=40, kind="clutch", one_way=True),
    "clutch_fg": dict(delta=0.10, min_n=30, kind="clutch", split=True),
    "ft_2nd": dict(delta=0.08, min_n=40, kind="ft", split=True),
    "side_3p": dict(delta=0.08, min_n=40, kind="side", split=True),
    "home_3p": dict(delta=0.07, min_n=60, kind="home", split=True),
    "home_fg": dict(delta=0.05, min_n=150, kind="home", split=True),
    "half_fg": dict(delta=0.07, min_n=60, kind="half", split=True),
    "b2b_fg": dict(delta=0.06, min_n=50, kind="b2b", split=True),
    "b2b_team": dict(delta=0.15, min_n=8, kind="b2b", split=True),
    "quarter_team": dict(delta=0.12, min_n=40, kind="quarter", split=True),
    "hot_hand": dict(delta=0.06, min_n=100, kind="hot", split=True),
}
TOUCH = {  # measure, touches column, prefix of the FGA / passes columns
    "elbow": ("ElbowTouch", "ELBOW_TOUCHES", "ELBOW_TOUCH"),
    "post": ("PostTouch", "POST_TOUCHES", "POST_TOUCH"),
    "paint": ("PaintTouch", "PAINT_TOUCHES", "PAINT_TOUCH"),
    "drive": ("Drives", "DRIVES", "DRIVE"),
}
ROLE_PEERS = 30          # how many of the closest players make up a role baseline
ROLE_MIN_MINUTES = 200   # this season plus last, so two weeks in a player's role still comes mostly from last year
PEER_MIN_N = 20          # a peer's own sample must be at least this big to count in the pooled rate
REG = "g.season = ? and g.season_type = 'Regular Season'"


def base_family(family: str) -> str:
    return family.split(":")[0]


def config(family: str) -> dict:
    return FAMILIES[base_family(family)]


def _flip_name(last_first: str) -> str:
    last, _, first = last_first.partition(",")
    return f"{first.strip()} {last.strip()}".strip() if first else last_first


def role_vectors(con: duckdb.DuckDBPyConnection, season: str) -> dict[int, np.ndarray]:
    """Standardised (shot volume, assists, rebounds per 36 minutes; height) per player, over this season and
    the one before."""
    rows = con.execute("""
        select pg.player_id, sum(pg.seconds) / 60.0, sum(pg.fga), sum(pg.fta), sum(pg.tov), sum(pg.ast),
               sum(pg.reb), any_value(pl.height)
        from player_games pg join games g using (game_id) left join players pl on pl.player_id = pg.player_id
        where g.season in (?, ?) and g.season_type = 'Regular Season' group by 1""",
                       [season, previous_season(season)]).fetchall()
    raw = {}
    for pid, mins, fga, fta, tov, ast, reb, height in rows:
        if not mins or mins < ROLE_MIN_MINUTES or not height or "-" not in height:
            continue
        feet, inches = height.split("-")
        raw[pid] = [((fga or 0) + 0.44 * (fta or 0) + (tov or 0)) * 36 / mins, (ast or 0) * 36 / mins,
                    (reb or 0) * 36 / mins, int(feet) * 12 + int(inches)]
    if len(raw) <= ROLE_PEERS:
        return {}
    x = np.array(list(raw.values()), dtype=float)
    x = (x - x.mean(0)) / x.std(0)
    return dict(zip(raw, x))


class Context:
    """Per-season lookups shared by the builders."""

    def __init__(self, con: duckdb.DuckDBPyConnection, season: str):
        self.con, self.season = con, season
        rows = con.execute(f"""
            select pg.player_id, any_value(pg.name), arg_max(pg.team_code, g.tip_utc), sum(pg.fg3a), sum(pg.fga)
            from player_games pg join games g using (game_id) where {REG} group by pg.player_id""",
                           [season]).fetchall()
        self.name = {r[0]: r[1] for r in rows}
        self.team = {r[0]: r[2] for r in rows}
        self.fg3a = {r[0]: r[3] for r in rows}
        self.role = role_vectors(con, season)

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


def _team_cand(family, ctx: Context, team_id, code, k, n, k0, n0, other="", **detail) -> dict:
    return dict(family=family, season=ctx.season, key="|".join([family, ctx.season, code, str(other)]),
                subject_id=team_id, subject=code, team=code, k=int(k), n=int(n), p0=k0 / n0, n0=n0,
                detail=dict(k0=int(k0), **detail))


def peer_baseline(ctx: Context, rows: list[tuple]) -> dict[int, tuple[float, list[str]]]:
    """For each (pid, k, n): the pooled k/n of his ROLE_PEERS closest players by role (never himself), and the
    names of the three closest."""
    pool = [(pid, k, n) for pid, k, n in rows if pid in ctx.role and n >= PEER_MIN_N]
    if len(pool) <= ROLE_PEERS:
        return {}
    ids = [pid for pid, _, _ in pool]
    roles = np.array([ctx.role[pid] for pid in ids])
    kk = np.array([k for _, k, _ in pool], dtype=float)
    nn = np.array([n for _, _, n in pool], dtype=float)
    out = {}
    for pid, _, _ in rows:
        if pid not in ctx.role:
            continue
        near = [i for i in np.argsort(np.linalg.norm(roles - ctx.role[pid], axis=1)) if ids[i] != pid][:ROLE_PEERS]
        out[pid] = (kk[near].sum() / nn[near].sum(), [ctx.name.get(ids[i], "") for i in near[:3]])
    return out


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


def assists(ctx: Context) -> list[dict]:
    """Share of P's assists that go to R, vs the share of everyone else's assists (to anyone but P) that go to R."""
    rows = ctx.con.execute("""
        select player_id, passer_id, ast from passes p
        where season = ? and as_of = (select max(as_of) from passes q
                                      where q.season = p.season and q.player_id = p.player_id)""",
                           [ctx.season]).fetchall()
    pairs = [(r, p, a or 0) for r, p, a in rows if r != p and ctx.team.get(r) and ctx.team.get(r) == ctx.team.get(p)]
    given, got, team = defaultdict(int), defaultdict(int), defaultdict(int)
    for r, p, a in pairs:
        given[p] += a; got[r] += a; team[ctx.team[p]] += a
    out = []
    for r, p, a in pairs:
        n0 = team[ctx.team[p]] - given[p] - got[p]
        if n0 > 0 and given[p]:
            out.append(_cand("ast_partner", ctx, p, a, given[p], (got[r] - a) / n0, n0=n0, other=r,
                             receiver=ctx.name.get(r, ""), k0=got[r] - a))
    return out


def touches(ctx: Context) -> list[dict]:
    out = []
    for touch, (measure, tcol, pre) in TOUCH.items():
        rows = ctx.dash(measure)
        names = {r["PLAYER_ID"]: r["PLAYER_NAME"] for r in rows}
        for action, col in (("shoot", f"{pre}_FGA"), ("pass", f"{pre}_PASSES")):
            data = [(r["PLAYER_ID"], r.get(col) or 0, r.get(tcol) or 0) for r in rows if r.get(tcol)]
            base = peer_baseline(ctx, data)
            for pid, k, n in data:
                if pid in base:
                    out.append(_cand(f"touch_{action}:{touch}", ctx, pid, k, n, base[pid][0], other=touch,
                                     group="touch", touch=touch, peers=base[pid][1], fallback_name=names[pid]))
    return out


def shooting_style(ctx: Context) -> list[dict]:
    cs = {r["PLAYER_ID"]: r for r in ctx.dash("CatchShoot")}
    pu = {r["PLAYER_ID"]: r for r in ctx.dash("PullUpShot")}
    out = []
    share = [(pid, r.get("CATCH_SHOOT_FG3A") or 0, ctx.fg3a.get(pid) or 0) for pid, r in cs.items()]
    share = [(pid, min(k, n), n) for pid, k, n in share if n]
    base = peer_baseline(ctx, share)
    for pid, k, n in share:
        if pid in base:
            out.append(_cand("cs_share", ctx, pid, k, n, base[pid][0], peers=base[pid][1],
                             fallback_name=cs[pid]["PLAYER_NAME"]))
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
    base = peer_baseline(ctx, data)
    names = {r["PLAYER_ID"]: r["PLAYER_NAME"] for r in rows}
    return [_cand("tight_fg", ctx, pid, k, n, base[pid][0], peers=base[pid][1], fallback_name=names[pid])
            for pid, k, n in data if pid in base]


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


def zones(ctx: Context) -> list[dict]:
    """Accuracy at the rim and from mid-range, against his role peers."""
    rows = ctx.con.execute("""
        select player_id, zone_basic, count(*) filter (where made), count(*) from shots
        where season = ? and season_type = 'Regular Season' and zone_basic in ('Restricted Area', 'Mid-Range')
        group by 1, 2""", [ctx.season]).fetchall()
    out = []
    for zone, tag in (("Restricted Area", "rim"), ("Mid-Range", "mid")):
        data = [(pid, k, n) for pid, z, k, n in rows if z == zone]
        base = peer_baseline(ctx, data)
        out += [_cand(f"zone_fg:{tag}", ctx, pid, k, n, base[pid][0], other=tag, zone=tag, peers=base[pid][1])
                for pid, k, n in data if pid in base]
    return out


# every field goal from play-by-play, flagged clutch: 4th quarter or overtime, last 5 minutes, within 5 points
# before the shot (the score on a made shot already includes it)
CLUTCH = f"""
    with p as (
        select p.game_id, p.team_id, p.person_id, p.period, p.location, p.shot_value, p.is_fg,
               p.shot_result = 'Made' as made,
               max(p.score_home) over w as sh, max(p.score_away) over w as sa,
               cast(regexp_extract(p.clock, 'PT([0-9]+)M', 1) as int) * 60
                 + cast(regexp_extract(p.clock, 'M([0-9.]+)S', 1) as double) as secs
        from pbp p join games g using (game_id) where {REG}
        window w as (partition by p.game_id order by p.action_number rows between unbounded preceding and current row)),
    s as (
        select game_id, team_id, person_id, made,
               coalesce(period >= 4 and secs <= 300 and abs(sh - sa - case when made then
                   (case when location = 'h' then shot_value else -shot_value end) else 0 end) <= 5, false) as clutch
        from p where is_fg and person_id is not null)"""


def clutch(ctx: Context) -> list[dict]:
    """Clutch accuracy against his own the rest of the time, after the league-wide clutch drop; and who takes
    over his team's shots."""
    acc = ctx.con.execute(CLUTCH + """
        select person_id, count(*) filter (where clutch and made), count(*) filter (where clutch),
               count(*) filter (where not clutch and made), count(*) filter (where not clutch)
        from s group by 1""", [ctx.season]).fetchall()
    out = []
    tot = np.array([r[1:] for r in acc], dtype=float).sum(0) if acc else np.zeros(4)
    if tot[1] and tot[3]:
        league_clutch, league_other = tot[0] / tot[1], tot[2] / tot[3]
        out += [_cand("clutch_fg", ctx, pid, k, n, k0 / n0 * league_clutch / league_other, n0=n0, k0=k0,
                      own=k0 / n0, league_clutch=league_clutch, league_other=league_other)
                for pid, k, n, k0, n0 in acc if n and n0]
    use = ctx.con.execute(CLUTCH + """,
        gp as (select game_id, player_id, team_id from player_games where seconds > 0),
        tm as (select game_id, team_id, count(*) filter (where clutch) as tc, count(*) filter (where not clutch) as tn
               from s group by 1, 2),
        me as (select game_id, person_id, count(*) filter (where clutch) as mc, count(*) filter (where not clutch) as mn
               from s group by 1, 2)
        select gp.player_id, sum(coalesce(me.mc, 0)), sum(tm.tc), sum(coalesce(me.mn, 0)), sum(tm.tn)
        from gp join tm using (game_id, team_id)
        left join me on me.game_id = gp.game_id and me.person_id = gp.player_id group by 1""",
                          [ctx.season]).fetchall()
    out += [_cand("clutch_usage", ctx, pid, k, n, k0 / n0, n0=n0, k0=k0) for pid, k, n, k0, n0 in use if n and n0]
    return out


def free_throws(ctx: Context) -> list[dict]:
    """Second free throw of two against the first."""
    rows = ctx.con.execute(f"""
        select p.person_id,
               count(*) filter (where p.sub_type = 'Free Throw 2 of 2' and p.made),
               count(*) filter (where p.sub_type = 'Free Throw 2 of 2'),
               count(*) filter (where p.sub_type = 'Free Throw 1 of 2' and p.made),
               count(*) filter (where p.sub_type = 'Free Throw 1 of 2')
        from (select *, description not ilike '%MISS%' as made from pbp where action_type = 'Free Throw') p
        join games g using (game_id) where {REG} group by 1""", [ctx.season]).fetchall()
    return [_cand("ft_2nd", ctx, pid, k, n, k0 / n0, n0=n0, k0=k0) for pid, k, n, k0, n0 in rows if n and n0]


def sides(ctx: Context) -> list[dict]:
    """Threes from the left side against the right (NBA's zone labels, facing the basket)."""
    rows = ctx.con.execute("""
        select player_id,
               count(*) filter (where zone_area like 'Left%' and made), count(*) filter (where zone_area like 'Left%'),
               count(*) filter (where zone_area like 'Right%' and made), count(*) filter (where zone_area like 'Right%')
        from shots where season = ? and season_type = 'Regular Season'
          and zone_basic in ('Left Corner 3', 'Right Corner 3', 'Above the Break 3') group by 1""",
                           [ctx.season]).fetchall()
    return [_cand("side_3p", ctx, pid, k, n, k0 / n0, n0=n0, k0=k0) for pid, k, n, k0, n0 in rows if n and n0]


def home_away(ctx: Context) -> list[dict]:
    by = defaultdict(dict)
    for pid, home, *v in ctx.con.execute(f"""
            select pg.player_id, pg.team_id = g.home_id, sum(pg.fg3m), sum(pg.fg3a), sum(pg.fgm), sum(pg.fga)
            from player_games pg join games g using (game_id)
            where {REG} and not coalesce(g.neutral, false) group by 1, 2""", [ctx.season]).fetchall():
        by[pid][home] = [x or 0 for x in v]
    out = []
    for pid, v in by.items():
        h, a = v.get(True), v.get(False)
        if not h or not a:
            continue
        if h[1] and a[1]:
            out.append(_cand("home_3p", ctx, pid, h[0], h[1], a[0] / a[1], n0=a[1], group="home", k0=a[0]))
        if h[3] and a[3]:
            out.append(_cand("home_fg", ctx, pid, h[2], h[3], a[2] / a[3], n0=a[3], group="home", k0=a[2]))
    return out


def halves(ctx: Context) -> list[dict]:
    """Second-half accuracy against the first half (overtime left out)."""
    rows = ctx.con.execute(f"""
        select p.person_id,
               count(*) filter (where p.period in (3, 4) and p.shot_result = 'Made'), count(*) filter (where p.period in (3, 4)),
               count(*) filter (where p.period in (1, 2) and p.shot_result = 'Made'), count(*) filter (where p.period in (1, 2))
        from pbp p join games g using (game_id) where {REG} and p.is_fg and p.person_id is not null group by 1""",
                           [ctx.season]).fetchall()
    return [_cand("half_fg", ctx, pid, k, n, k0 / n0, n0=n0, k0=k0) for pid, k, n, k0, n0 in rows if n and n0]


def _team_games(ctx: Context) -> list[tuple]:
    """(game_id, team_id, code, won, second night of a back-to-back) for every finished regular-season game."""
    return ctx.con.execute(f"""
        with t as (
            select game_id, game_date, home_id as team_id, home_code as code, home_score > away_score as won
            from games g where {REG} and status = 3
            union all
            select game_id, game_date, away_id, away_code, away_score > home_score from games g where {REG} and status = 3)
        select game_id, team_id, code, won,
               coalesce(date_diff('day', lag(game_date) over (partition by team_id order by game_date), game_date) = 1,
                        false)
        from t""", [ctx.season, ctx.season]).fetchall()


def back_to_back(ctx: Context) -> list[dict]:
    """Second nights of back-to-backs against every other game: team wins, player FG%."""
    team, b2b = defaultdict(lambda: [0, 0, 0, 0]), set()
    for gid, tid, code, won, second in _team_games(ctx):
        t, i = team[(tid, code)], (0 if second else 2)
        t[i] += won; t[i + 1] += 1
        if second:
            b2b.add((gid, tid))
    out = [_team_cand("b2b_team", ctx, tid, code, *t) for (tid, code), t in team.items() if t[1] and t[3]]
    player = defaultdict(lambda: [0, 0, 0, 0])
    for gid, tid, pid, fgm, fga in ctx.con.execute(f"""
            select pg.game_id, pg.team_id, pg.player_id, pg.fgm, pg.fga from player_games pg join games g using (game_id)
            where {REG}""", [ctx.season]).fetchall():
        t, i = player[pid], (0 if (gid, tid) in b2b else 2)
        t[i] += fgm or 0; t[i + 1] += fga or 0
    out += [_cand("b2b_fg", ctx, pid, k, n, k0 / n0, n0=n0, k0=k0) for pid, (k, n, k0, n0) in player.items() if n and n0]
    return out


def quarters(ctx: Context) -> list[dict]:
    """Quarters a team wins, one quarter against its other three (ties left out)."""
    rows = ctx.con.execute(f"""
        with s as (
            select p.game_id, p.period, max(p.score_home) as sh, max(p.score_away) as sa
            from pbp p join games g using (game_id) where {REG} and g.status = 3 and p.period <= 4 group by 1, 2),
        e as (select game_id, period, max(sh) over w as sh, max(sa) over w as sa from s
              window w as (partition by game_id order by period rows between unbounded preceding and current row))
        select e.period, g.home_id, g.home_code, g.away_id, g.away_code,
               e.sh - coalesce(lag(e.sh) over (partition by e.game_id order by e.period), 0),
               e.sa - coalesce(lag(e.sa) over (partition by e.game_id order by e.period), 0)
        from e join games g using (game_id)""", [ctx.season]).fetchall()
    won = defaultdict(lambda: defaultdict(lambda: [0, 0]))     # (team_id, code) -> quarter -> [won, decided]
    for q, hid, hc, aid, ac, hp, ap in rows:
        if hp is None or ap is None or hp == ap:
            continue
        for team, mine, theirs in (((hid, hc), hp, ap), ((aid, ac), ap, hp)):
            w = won[team][q]
            w[0] += mine > theirs; w[1] += 1
    out = []
    for (tid, code), by_q in won.items():
        for q, (k, n) in by_q.items():
            k0, n0 = sum(v[0] for x, v in by_q.items() if x != q), sum(v[1] for x, v in by_q.items() if x != q)
            if n and n0:
                out.append(_team_cand("quarter_team", ctx, tid, code, k, n, k0, n0, other=q, quarter=q))
    return out


def hot_hand(ctx: Context) -> list[dict]:
    """The shot right after a make against the shot right after a miss (same player, same game)."""
    rows = ctx.con.execute(f"""
        with s as (
            select p.person_id, p.shot_result = 'Made' as made,
                   lag(p.shot_result = 'Made') over (partition by p.game_id, p.person_id order by p.action_number) as prev
            from pbp p join games g using (game_id) where {REG} and p.is_fg and p.person_id is not null)
        select person_id, count(*) filter (where prev and made), count(*) filter (where prev),
               count(*) filter (where not prev and made), count(*) filter (where not prev)
        from s where prev is not null group by 1""", [ctx.season]).fetchall()
    return [_cand("hot_hand", ctx, pid, k, n, k0 / n0, n0=n0, k0=k0) for pid, k, n, k0, n0 in rows if n and n0]


BUILDERS = [passes, assists, touches, shooting_style, tight_defense, corners, zones, clutch, free_throws, sides,
            home_away, halves, back_to_back, quarters, hot_hand]


def candidates(con: duckdb.DuckDBPyConnection, season: str) -> list[dict]:
    ctx = Context(con, season)
    out: list[dict] = []
    for build in BUILDERS:
        out += build(ctx)
    return out

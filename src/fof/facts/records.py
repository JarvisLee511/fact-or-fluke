"""'Record' fun facts: what happened last night, and how rare it is across every game in the database."""
from __future__ import annotations

import duckdb

SEASON_TYPES = ("Regular Season", "Playoffs", "PlayIn")
UNITS = {"pts": ("分", "points"), "reb": ("籃板", "rebounds"), "ast": ("助攻", "assists"),
         "stl": ("抄截", "steals"), "blk": ("阻攻", "blocks"), "fg3m": ("記三分", "threes")}
SINGLE = {"pts": 40, "reb": 18, "ast": 14, "stl": 6, "blk": 6, "fg3m": 8}
COMBOS = [(("pts", "reb", "ast"), (10, 10, 10)), (("fg3m", "blk"), (4, 4)), (("pts", "ast"), (30, 10)),
          (("reb", "ast"), (12, 10)), (("stl", "blk"), (4, 4))]
PERFECT_MIN_FGA = 8


def _count(con, where: str, params: list) -> int:
    return con.execute(f"""select count(*) from player_games pg join games g using (game_id)
                           where g.season_type in {SEASON_TYPES} and {where}""", params).fetchone()[0]


def _line(stats: tuple[str, ...], vals: tuple[int, ...]) -> tuple[str, str]:
    if stats == ("pts", "reb", "ast"):
        return (f"大三元：{vals[0]} 分 {vals[1]} 籃板 {vals[2]} 助攻",
                f"triple-double: {vals[0]} pts, {vals[1]} reb, {vals[2]} ast")
    return (" + ".join(f"{v} {UNITS[s][0]}" for s, v in zip(stats, vals)),
            " + ".join(f"{v} {UNITS[s][1]}" for s, v in zip(stats, vals)))


def last_night(con: duckdb.DuckDBPyConnection, day, top: int = 5) -> list[dict]:
    since = con.execute("""select min(g.season) from player_games pg join games g using (game_id)""").fetchone()[0]
    lines = con.execute(f"""
        select pg.player_id, pg.name, pg.team_code, pg.game_id, pg.pts, pg.reb, pg.ast, pg.stl, pg.blk, pg.fg3m,
               pg.fgm, pg.fga
        from player_games pg join games g using (game_id)
        where g.game_date = ? and g.season_type in {SEASON_TYPES} and not pg.dnp""", [day]).fetchall()
    found = []
    for pid, name, team, gid, *vals in lines:
        s = dict(zip(["pts", "reb", "ast", "stl", "blk", "fg3m", "fgm", "fga"], vals))
        options = [((k,), (s[k],)) for k, lo in SINGLE.items() if s[k] >= lo]
        options += [(c, tuple(s[x] for x in c)) for c, los in COMBOS if all(s[x] >= lo for x, lo in zip(c, los))]
        for stats, v in options:
            n = _count(con, " and ".join(f"pg.{x} >= ?" for x in stats), list(v))
            zh, en = _line(stats, v)
            found.append(dict(player_id=pid, name=name, team=team, game_id=gid, count=n, zh=zh, en=en,
                              size=sum(x / max(SINGLE.get(k, 1), 1) for k, x in zip(stats, v))))
        if s["fga"] >= PERFECT_MIN_FGA and s["fgm"] == s["fga"]:
            n = _count(con, "pg.fga >= ? and pg.fgm = pg.fga", [s["fga"]])
            found.append(dict(player_id=pid, name=name, team=team, game_id=gid, count=n,
                              zh=f"投籃 {s['fgm']} 投 {s['fgm']} 中，一球沒失手",
                              en=f"perfect {s['fgm']}-for-{s['fga']} shooting", size=s["fga"] / PERFECT_MIN_FGA))
    best: dict[int, dict] = {}
    for r in sorted(found, key=lambda r: (r["count"], -r["size"])):
        best.setdefault(r["player_id"], r)          # one record per player: the rarest
    out = sorted(best.values(), key=lambda r: (r["count"], -r["size"]))[:top]
    for r in out:
        nth = "第一次" if r["count"] == 1 else f"第 {r['count']} 次"
        en_nth = "the first time" if r["count"] == 1 else f"only the {_ordinal(r['count'])} time"
        r["text_zh"] = f"{r['name']}（{r['team']}）{r['zh']}，{since} 季以來{nth}"
        r["text_en"] = f"{r['name']} ({r['team']}): {r['en']}, {en_nth} since the start of {since}"
    return out


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

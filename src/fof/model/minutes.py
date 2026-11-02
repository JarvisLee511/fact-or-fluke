"""Expected minutes per player for every team-game, under five states of knowledge:

morning  who played for the team lately, and how often a player missing his team's last k games plays the
         next
report   the same plus the official injury report the morning run can read (the last one out by 08:00 ET
         on game day that lists the game): a listed player plays as often as players with his status did,
         an unlisted one as often as unlisted players with his run of missed games; games without a report
         (before 2020) keep the morning numbers
active   the official active list (the box score's players: inactive ones are not listed), published about
         30 minutes before tip
lineup   the active list and the starting fives (also out about 30 minutes before tip): a player's minutes
         come from his recent games in tonight's role, starting or off the bench
oracle   the minutes actually played: an upper bound, perfect knowledge of who plays and for how long

A player's minutes when he plays come from his recent games (any team), recent ones weighted more. Each
team's expected minutes are scaled to 240, five players for 48 minutes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timezone

import duckdb

from ..config import ET
from ..store.stints import bare, norm

DECAY = 0.85                 # weight of each earlier game in a player's minutes when he plays
ROOKIE_MIN = 12.0            # a player with no earlier game
STARTER_MIN = 24.0           # at least this for a starter with no earlier start
RECENT = 10                  # the morning roster: played for the team in its last RECENT games
STREAK_CAP = 10
STATUSES = ["Out", "Doubtful", "Questionable", "Probable", "Available"]
MORNING = time(8, 0)         # ET, the morning run


def team_games(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    """(game_id, season, team_id, [(player_id, seconds, started)]) for every team-game, in tip order."""
    rows = con.execute("""
        select pg.game_id, g.season, pg.team_id,
               list((pg.player_id, coalesce(pg.seconds, 0), coalesce(pg.starter, false)) order by pg.player_id)
        from player_games pg join games g using (game_id)
        where g.status = 3 and g.season_type in ('Regular Season', 'Playoffs', 'PlayIn')
        group by pg.game_id, g.season, pg.team_id, g.tip_utc order by g.tip_utc, pg.game_id, pg.team_id""").fetchall()
    return [(gid, season, tid, [(int(p), int(s), bool(st)) for p, s, st in box]) for gid, season, tid, box in rows]


def play_rates(games: list[tuple], seasons: set[str]) -> dict[int, float]:
    """P(plays | missed his team's last k games) for k = 0..STREAK_CAP, counted over `seasons`."""
    streak: dict[tuple[int, int], int] = {}
    last_team: dict[int, int] = {}
    roster: dict[int, list[set[int]]] = defaultdict(list)
    seen, played = defaultdict(int), defaultdict(int)
    for _, season, tid, box in games:
        on = {p for p, s, _ in box if s > 0}
        recent = set().union(*roster[tid][-RECENT:]) if roster[tid] else set()
        if season in seasons:
            for p in recent:
                if last_team.get(p) == tid:
                    k = min(streak.get((p, tid), 0), STREAK_CAP)
                    seen[k] += 1
                    played[k] += p in on
        for p in recent | on:
            if last_team.get(p, tid) == tid or p in on:
                streak[(p, tid)] = 0 if p in on else streak.get((p, tid), 0) + 1
        for p in on:
            last_team[p] = tid
        roster[tid].append(on)
    return {k: played[k] / seen[k] for k in seen}


def expected(games: list[tuple], rates: dict[int, float], status: dict | None = None,
             report_rates: dict | None = None) -> dict[str, dict[tuple[str, int], dict[int, float]]]:
    """{mode: {(game_id, team_id): {player_id: minutes}}} for each mode, each known before its game. `status`
    and `report_rates` come from report_status and play_rates_with_report."""
    ewma: dict[int, float] = {}
    role: dict[tuple[int, bool], float] = {}     # (player, started) -> minutes
    streak: dict[tuple[int, int], int] = {}
    last_team: dict[int, int] = {}
    roster: dict[int, list[set[int]]] = defaultdict(list)
    out = {"morning": {}, "report": {}, "active": {}, "lineup": {}, "oracle": {}}
    status = status or {}

    def scaled(m: dict[int, float]) -> dict[int, float]:
        total = sum(m.values())
        return {p: v * 240.0 / total for p, v in m.items()} if total else m

    for gid, _, tid, box in games:
        listed = [p for p, _, _ in box]
        on = {p for p, s, _ in box if s > 0}
        recent = set().union(*roster[tid][-RECENT:]) if roster[tid] else set()
        out["oracle"][(gid, tid)] = scaled({p: s / 60.0 for p, s, _ in box if s > 0})
        out["active"][(gid, tid)] = scaled({p: ewma.get(p, ROOKIE_MIN) for p in listed})
        out["lineup"][(gid, tid)] = scaled({
            p: role.get((p, st), max(ewma.get(p, ROOKIE_MIN), STARTER_MIN) if st else ewma.get(p, ROOKIE_MIN))
            for p, _, st in box})
        mine = [p for p in recent if last_team.get(p) == tid]
        out["morning"][(gid, tid)] = scaled({
            p: ewma.get(p, ROOKIE_MIN) * rates.get(min(streak.get((p, tid), 0), STREAK_CAP), 0.0) for p in mine})
        listed_now = status.get((gid, tid))
        if listed_now is None or not report_rates or not report_rates["status"]:
            out["report"][(gid, tid)] = out["morning"][(gid, tid)]
        else:
            def chance(p: int) -> float:
                k = min(streak.get((p, tid), 0), STREAK_CAP)
                if p in listed_now:
                    return report_rates["status"].get(listed_now[p], rates.get(k, 0.0))
                return report_rates["unlisted"].get(k, rates.get(k, 0.0))
            out["report"][(gid, tid)] = scaled({p: ewma.get(p, ROOKIE_MIN) * chance(p)
                                                for p in set(mine) | set(listed_now)})
        for p, s, st in box:
            if s > 0:
                ewma[p] = s / 60.0 if p not in ewma else DECAY * ewma[p] + (1 - DECAY) * s / 60.0
                k = (p, st)
                role[k] = s / 60.0 if k not in role else DECAY * role[k] + (1 - DECAY) * s / 60.0
        for p in recent | on:
            if last_team.get(p, tid) == tid or p in on:
                streak[(p, tid)] = 0 if p in on else streak.get((p, tid), 0) + 1
        for p in on:
            last_team[p] = tid
        roster[tid].append(on)
    return out


def report_status(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, int], dict[int, str]]:
    """{(game_id, team_id): {player_id: status}} from the last injury report out by 08:00 ET on game day that
    lists the game, for each team that filed. Report names are matched to the players who played for the team
    that season."""
    games = con.execute("""select game_id, season, game_date, home_id, away_id, home_code, away_code from games
                           where status = 3""").fetchall()
    reports: dict[tuple, set] = defaultdict(set)
    lines: dict[tuple, list[tuple[str, str, str]]] = defaultdict(list)
    for at, gdate, matchup, team, name, st in con.execute("""
            select report_at, try_strptime(game_date, '%m/%d/%Y')::date as day, matchup, team_code, player_name, status
            from injuries where day is not null""").fetchall():
        reports[(gdate, matchup)].add(at)
        lines[(at, gdate, matchup)].append((team, name, st))
    names: dict[tuple[str, int], dict[str, int]] = defaultdict(dict)
    for season, tid, pid, name in con.execute("""
            select distinct g.season, pg.team_id, pg.player_id, pg.name from player_games pg join games g using (game_id)
            """).fetchall():
        names[(season, tid)].setdefault(norm(name), pid)
        names[(season, tid)].setdefault(norm(bare(name)), pid)
    out = {}
    for gid, season, day, home, away, hc, ac in games:
        key = (day, f"{ac}@{hc}")
        cutoff = datetime.combine(day, MORNING, ET).astimezone(timezone.utc).replace(tzinfo=None)
        before = [t for t in reports.get(key, ()) if t <= cutoff]
        if not before:
            continue
        rows = lines[(max(before), *key)]
        for tid, code in ((home, hc), (away, ac)):
            mine = [(n, st) for team, n, st in rows if team == code]
            if not mine or any(st == "Not Yet Submitted" for _, st in mine):
                continue
            idx = names.get((season, tid), {})
            found = {}
            for n, st in mine:
                pid = idx.get(norm(n), idx.get(norm(bare(n))))
                if pid is not None and st in STATUSES:
                    found[pid] = st
            out[(gid, tid)] = found
    return out


def play_rates_with_report(games: list[tuple], status: dict, seasons: set[str]) -> dict:
    """How often listed players played, by status, and unlisted ones, by run of missed games, over `seasons`."""
    streak: dict[tuple[int, int], int] = {}
    last_team: dict[int, int] = {}
    roster: dict[int, list[set[int]]] = defaultdict(list)
    seen: dict = defaultdict(int)
    played: dict = defaultdict(int)
    for gid, season, tid, box in games:
        on = {p for p, s, _ in box if s > 0}
        recent = set().union(*roster[tid][-RECENT:]) if roster[tid] else set()
        listed = status.get((gid, tid))
        if season in seasons and listed is not None:
            for p in set(listed) | {p for p in recent if last_team.get(p) == tid}:
                key = ("status", listed[p]) if p in listed else ("unlisted", min(streak.get((p, tid), 0), STREAK_CAP))
                seen[key] += 1
                played[key] += p in on
        for p in recent | on:
            if last_team.get(p, tid) == tid or p in on:
                streak[(p, tid)] = 0 if p in on else streak.get((p, tid), 0) + 1
        for p in on:
            last_team[p] = tid
        roster[tid].append(on)
    out: dict = {"status": {}, "unlisted": {}}
    for (kind, k), n in seen.items():
        out[kind][k] = played[(kind, k)] / n
    return out

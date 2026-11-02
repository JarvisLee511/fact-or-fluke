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

The daily run (tonight) uses report mode for games not played yet, with today's rosters from the league's
player index.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timezone

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
NOT_ABSENT = ("G League",)   # listed for a roster move, not an injury or absence


class Tracker:
    """What the box scores so far say about each player, one team-game at a time: his minutes when he plays
    (recent games weighted more), the same by role (starting or off the bench), how many of his team's games
    in a row he has missed, his last team, and each team's recent rosters."""

    def __init__(self) -> None:
        self.ewma: dict[int, float] = {}
        self.role: dict[tuple[int, bool], float] = {}     # (player, started) -> minutes
        self.streak: dict[tuple[int, int], int] = {}
        self.last_team: dict[int, int] = {}
        self.roster: dict[int, list[set[int]]] = defaultdict(list)

    def recent(self, tid: int) -> set[int]:
        return set().union(*self.roster[tid][-RECENT:]) if self.roster[tid] else set()

    def mine(self, tid: int) -> list[int]:
        """The morning roster: played for the team in one of its last RECENT games, and for no team since."""
        return [p for p in self.recent(tid) if self.last_team.get(p) == tid]

    def missed(self, p: int, tid: int) -> int:
        return min(self.streak.get((p, tid), 0), STREAK_CAP)

    def minutes(self, p: int) -> float:
        return self.ewma.get(p, ROOKIE_MIN)

    def add(self, tid: int, box: list[tuple[int, int, bool]]) -> None:
        on = {p for p, s, _ in box if s > 0}
        recent = self.recent(tid)
        for p, s, st in box:
            if s > 0:
                self.ewma[p] = s / 60.0 if p not in self.ewma else DECAY * self.ewma[p] + (1 - DECAY) * s / 60.0
                k = (p, st)
                self.role[k] = s / 60.0 if k not in self.role else DECAY * self.role[k] + (1 - DECAY) * s / 60.0
        for p in recent | on:
            if self.last_team.get(p, tid) == tid or p in on:
                self.streak[(p, tid)] = 0 if p in on else self.streak.get((p, tid), 0) + 1
        for p in on:
            self.last_team[p] = tid
        self.roster[tid].append(on)


def _scaled(m: dict[int, float]) -> dict[int, float]:
    total = sum(m.values())
    return {p: v * 240.0 / total for p, v in m.items()} if total else m


def _chance(t: Tracker, p: int, tid: int, rates: dict, listed: dict[int, str], report_rates: dict) -> float:
    """How often a player like this one played: by his report status if listed, else by his run of missed
    games (counted on team `tid`)."""
    k = t.missed(p, tid)
    if p in listed:
        return report_rates["status"].get(listed[p], rates.get(k, 0.0))
    return report_rates["unlisted"].get(k, rates.get(k, 0.0))


def team_games(con: duckdb.DuckDBPyConnection, before: date | None = None) -> list[tuple]:
    """(game_id, season, team_id, [(player_id, seconds, started)]) for every team-game (played before
    `before`, if given), in tip order."""
    rows = con.execute("""
        select pg.game_id, g.season, pg.team_id,
               list((pg.player_id, coalesce(pg.seconds, 0), coalesce(pg.starter, false)) order by pg.player_id)
        from player_games pg join games g using (game_id)
        where g.status = 3 and g.season_type in ('Regular Season', 'Playoffs', 'PlayIn') and g.game_date < ?
        group by pg.game_id, g.season, pg.team_id, g.tip_utc order by g.tip_utc, pg.game_id, pg.team_id""",
                       [before or date.max]).fetchall()
    return [(gid, season, tid, [(int(p), int(s), bool(st)) for p, s, st in box]) for gid, season, tid, box in rows]


def play_rates(games: list[tuple], seasons: set[str]) -> dict[int, float]:
    """P(plays | missed his team's last k games) for k = 0..STREAK_CAP, counted over `seasons`."""
    t = Tracker()
    seen, played = defaultdict(int), defaultdict(int)
    for _, season, tid, box in games:
        if season in seasons:
            on = {p for p, s, _ in box if s > 0}
            for p in t.mine(tid):
                k = t.missed(p, tid)
                seen[k] += 1
                played[k] += p in on
        t.add(tid, box)
    return {k: played[k] / seen[k] for k in seen}


def expected(games: list[tuple], rates: dict[int, float], status: dict | None = None,
             report_rates: dict | None = None) -> dict[str, dict[tuple[str, int], dict[int, float]]]:
    """{mode: {(game_id, team_id): {player_id: minutes}}} for each mode, each known before its game. `status`
    and `report_rates` come from report_status and play_rates_with_report."""
    t = Tracker()
    out = {"morning": {}, "report": {}, "active": {}, "lineup": {}, "oracle": {}}
    status = status or {}
    for gid, _, tid, box in games:
        out["oracle"][(gid, tid)] = _scaled({p: s / 60.0 for p, s, _ in box if s > 0})
        out["active"][(gid, tid)] = _scaled({p: t.minutes(p) for p, _, _ in box})
        out["lineup"][(gid, tid)] = _scaled({
            p: t.role.get((p, st), max(t.minutes(p), STARTER_MIN) if st else t.minutes(p)) for p, _, st in box})
        mine = t.mine(tid)
        out["morning"][(gid, tid)] = _scaled({p: t.minutes(p) * rates.get(t.missed(p, tid), 0.0) for p in mine})
        listed_now = status.get((gid, tid))
        if listed_now is None or not report_rates or not report_rates["status"]:
            out["report"][(gid, tid)] = out["morning"][(gid, tid)]
        else:
            out["report"][(gid, tid)] = _scaled({p: t.minutes(p) * _chance(t, p, tid, rates, listed_now, report_rates)
                                                 for p in set(mine) | set(listed_now)})
        t.add(tid, box)
    return out


def tonight(t: Tracker, tid: int, rates: dict[int, float], report_rates: dict, roster: set[int] | None = None,
            listed: dict[int, tuple[str, str]] | None = None) -> dict[str, dict[int, float]]:
    """A team's next game, from what `t` has seen so far: report-mode minutes, and the same with everyone
    listed for an injury or absence playing as often as a healthy player (full: what the absences cost).

    `roster` (the league's player index: who is on the team today) drops players who have left since their
    last game here and adds the ones who have joined, whose run of missed games comes from their last team.
    `listed` is {player: (status, reason)} from today's report; None (no report yet) keeps the morning
    numbers, and then the absences cost nothing."""
    mine = t.mine(tid)
    team = {p: tid for p in mine}
    if roster is not None:
        mine = [p for p in mine if p in roster]
        team = {p: tid for p in mine}
        for p in sorted(roster):
            last = t.last_team.get(p)
            if p not in team and p in t.ewma and last is not None and last != tid:
                team[p] = last
    if listed is None or not report_rates or not report_rates["status"]:
        m = _scaled({p: t.minutes(p) * rates.get(t.missed(p, team[p]), 0.0) for p in team})
        return {"report": m, "full": m}
    status = {p: st for p, (st, _) in listed.items()}
    absent = {p for p, (_, why) in listed.items() if not why.startswith(NOT_ABSENT) and p in t.ewma}
    healthy = report_rates["unlisted"].get(0, rates.get(0, 0.0))
    players = set(team) | set(listed)
    report = {p: t.minutes(p) * _chance(t, p, team.get(p, tid), rates, status, report_rates) for p in players}
    full = {p: t.minutes(p) * healthy if p in absent else v for p, v in report.items()}
    return {"report": _scaled(report), "full": _scaled(full)}


def _team_status(rows: list[tuple[str, str, str, str]], code: str, idx: dict[str, int]) -> dict | None:
    """{player_id: (status, reason)} for one team's lines on a report; None if the team has not filed."""
    mine = [(n, st, why) for team, n, st, why in rows if team == code]
    if not mine or any(st == "Not Yet Submitted" for _, st, _ in mine):
        return None
    found = {}
    for n, st, why in mine:
        pid = idx.get(norm(n), idx.get(norm(bare(n))))
        if pid is not None and st in STATUSES:
            found[pid] = (st, why)
    return found


def _reports(con: duckdb.DuckDBPyConnection, since: date | None = None) -> tuple[dict, dict]:
    """Report times per (game day, matchup), and each report's lines per game."""
    reports: dict[tuple, set] = defaultdict(set)
    lines: dict[tuple, list[tuple[str, str, str, str]]] = defaultdict(list)
    for at, gdate, matchup, team, name, st, why in con.execute("""
            select report_at, try_strptime(game_date, '%m/%d/%Y')::date as day, matchup, team_code, player_name,
                   status, coalesce(reason, '')
            from injuries where day is not null and day >= ?""", [since or date.min]).fetchall():
        reports[(gdate, matchup)].add(at)
        lines[(at, gdate, matchup)].append((team, name, st, why))
    return reports, lines


def report_status(con: duckdb.DuckDBPyConnection) -> dict[tuple[str, int], dict[int, str]]:
    """{(game_id, team_id): {player_id: status}} from the last injury report out by 08:00 ET on game day that
    lists the game, for each team that filed. Report names are matched to the players who played for the team
    that season."""
    games = con.execute("""select game_id, season, game_date, home_id, away_id, home_code, away_code from games
                           where status = 3""").fetchall()
    reports, lines = _reports(con)
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
            found = _team_status(rows, code, names.get((season, tid), {}))
            if found is not None:
                out[(gid, tid)] = {p: st for p, (st, _) in found.items()}
    return out


def today_status(con: duckdb.DuckDBPyConnection, games: list[dict], as_of: datetime,
                 rosters: dict[int, set[int]] | None = None) -> tuple[dict, dict[str, str]]:
    """For games not played yet (dicts with game_id, season, game_date, home/away id and code): {(game_id,
    team_id): {player_id: (status, reason)}} from the last report out by `as_of` that lists the game, for each
    team that filed, and {game_id: when that report came out (ET), if either team had filed}. Names are matched
    to today's rosters first, then to the players who have played for the team this season."""
    if not games:
        return {}, {}
    reports, lines = _reports(con, min(g["game_date"] for g in games))
    names: dict[int, dict[str, int]] = defaultdict(dict)
    team_of = {p: tid for tid, members in (rosters or {}).items() for p in members}
    for pid, name in con.execute("select player_id, name from players").fetchall():
        if pid in team_of:
            names[team_of[pid]].setdefault(norm(name), pid)
            names[team_of[pid]].setdefault(norm(bare(name)), pid)
    for tid, pid, name in con.execute("""
            select distinct pg.team_id, pg.player_id, pg.name from player_games pg join games g using (game_id)
            where g.season = ?""", [games[0]["season"]]).fetchall():
        names[tid].setdefault(norm(name), pid)
        names[tid].setdefault(norm(bare(name)), pid)
    cutoff = as_of.astimezone(timezone.utc).replace(tzinfo=None)
    out, stamps = {}, {}
    for g in games:
        key = (g["game_date"], f"{g['away_code']}@{g['home_code']}")
        before = [t for t in reports.get(key, ()) if t <= cutoff]
        if not before:
            continue
        at = max(before)
        rows = lines[(at, *key)]
        for side in ("home", "away"):
            found = _team_status(rows, g[f"{side}_code"], names.get(g[f"{side}_id"], {}))
            if found is not None:
                out[(g["game_id"], g[f"{side}_id"])] = found
                stamps[g["game_id"]] = at.replace(tzinfo=timezone.utc).astimezone(ET).isoformat()
    return out, stamps


def play_rates_with_report(games: list[tuple], status: dict, seasons: set[str]) -> dict:
    """How often listed players played, by status, and unlisted ones, by run of missed games, over `seasons`."""
    t = Tracker()
    seen: dict = defaultdict(int)
    played: dict = defaultdict(int)
    for gid, season, tid, box in games:
        listed = status.get((gid, tid))
        if season in seasons and listed is not None:
            on = {p for p, s, _ in box if s > 0}
            for p in set(listed) | set(t.mine(tid)):
                key = ("status", listed[p]) if p in listed else ("unlisted", t.missed(p, tid))
                seen[key] += 1
                played[key] += p in on
        t.add(tid, box)
    out: dict = {"status": {}, "unlisted": {}}
    for (kind, k), n in seen.items():
        out[kind][k] = played[(kind, k)] / n
    return out

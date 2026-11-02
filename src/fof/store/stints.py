"""Lineup stints rebuilt from play-by-play: which ten players were on the floor for every stretch of a game,
and the points and possessions each side had in it.

Play-by-play gives the player leaving a substitution by id, but the one coming in only by family name, and a
player can go a whole quarter without an event of his own. So:
- the 1st period starts with the box score starters;
- a later period starts with the players seen before they come in (or who go out first), topped up from the
  previous period's closing five, then by minutes played;
- a family name two teammates share goes to the one not on the floor, then to the one who shows up first;
- the box score has today's names but old play-by-play the names of the day, so an incoming name is matched
  exactly, then without a Jr. / III suffix ("Butler" = Jimmy Butler III), then by first-name prefix ("Mark
  Morris" = Markieff Morris), then to the teammate whose own events are spelled that way ("Kanter" = Enes Freedom).
Every game is checked against its box score: five a side in every stint, each player's minutes within a
minute of his box score, and the play-by-play score ending on the final score. Games that fail stay in the
table, flagged in stint_checks, so the player model can leave them out.
"""
from __future__ import annotations

import bisect
import logging
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

import duckdb

from . import db

PERIOD_S, OT_S = 720, 300
TOLERANCE_S = 60            # reconstructed minutes may differ from the box score by this much per player
NOT_ON_FLOOR = {"Timeout", "Instant Replay", "Ejection", "period", ""}   # events that do not prove who is playing
PBP_COLS = ("game_id, action_number, period, clock, team_id, person_id, action_type, sub_type, description, "
            "is_fg, shot_result, score_home, score_away")
SUFFIXES = {"Jr.", "Jr", "Sr.", "Sr", "II", "III", "IV"}

log = logging.getLogger(__name__)


@dataclass
class Act:
    period: int
    clock: str
    team: int
    person: int
    kind: str
    sub_type: str
    desc: str
    is_fg: bool
    made: bool
    score_home: int | None
    score_away: int | None


def act(row: tuple) -> Act:
    _, _, period, clock, team, person, kind, sub_type, desc, is_fg, result, sh, sa = row
    desc = desc or ""
    made = result == "Made" if is_fg else kind == "Free Throw" and "MISS" not in desc.upper()
    return Act(period or 0, clock or "", team or 0, person or 0, kind or "", sub_type or "", desc, bool(is_fg), made,
               sh, sa)


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


def bare(name: str) -> str:
    """'Butler III' -> 'Butler', 'Boston Jr.' -> 'Boston'."""
    head, _, tail = name.rpartition(" ")
    return head if head and tail in SUFFIXES else name


def clock_left(clock: str) -> float | None:
    """'PT11M34.00S' -> 694.0 seconds left in the period."""
    if not clock.startswith("PT"):
        return None
    m, _, s = clock[2:].rstrip("S").partition("M")
    return int(m or 0) * 60 + float(s or 0)


def period_start(p: int) -> float:
    return (p - 1) * PERIOD_S if p <= 4 else 4 * PERIOD_S + (p - 5) * OT_S


def period_end(p: int) -> float:
    return period_start(p) + (PERIOD_S if p <= 4 else OT_S)


def incoming(desc: str) -> str:
    """'SUB: Smith Jr. FOR Green' -> 'Smith Jr.'"""
    return desc.removeprefix("SUB: ").rpartition(" FOR ")[0]


def last_of_trip(sub_type: str) -> bool:
    """'Free Throw 2 of 2' -> True; technicals never end a possession."""
    words = sub_type.split()
    return len(words) >= 3 and words[-2] == "of" and words[-3] == words[-1]


def game(home: int, away: int, acts: list[Act], players: dict[int, tuple[int, bool, int, str, str]],
         final: tuple[int, int]) -> tuple[list[dict], dict]:
    """-> (stints, check) for one game. players: {pid: (team_id, starter, box seconds, family name, full name)}."""
    # game-clock order, not entry order: a substitution is sometimes entered minutes after it happened
    timed, left_at = [], {}
    for i, a in enumerate(acts):
        left = clock_left(a.clock)
        left = left_at.get(a.period, PERIOD_S if a.period <= 4 else OT_S) if left is None else left
        left_at[a.period] = left
        timed.append((a.period, -left, i, a))
    acts = [t[3] for t in sorted(timed, key=lambda t: t[:3])]
    teams = (home, away)
    names: dict[int, dict[str, list[int]]] = {t: defaultdict(list) for t in teams}
    bare_names: dict[int, dict[str, list[int]]] = {t: defaultdict(list) for t in teams}
    first_names: dict[int, dict[str, list[int]]] = {t: defaultdict(list) for t in teams}
    first: dict[int, str] = {}
    for pid, (team, _, _, family, full) in players.items():
        first[pid] = norm(full[: len(full) - len(family)] if family and full.endswith(family) else full.split(" ")[0])
        if team in names:
            names[team][norm(family)].append(pid)
            names[team][norm(full)].append(pid)
            bare_names[team][norm(bare(family))].append(pid)
            bare_names[team][norm(bare(full))].append(pid)
            # some players go by one name ("Hansen"), but a family name wins: "Allen" is Jarrett Allen, not
            # his teammate Allen Crabbe
            first_names[team][first[pid]].append(pid)
    seen: dict[int, list[int]] = defaultdict(list)
    for i, a in enumerate(acts):
        if a.person:
            seen[a.person].append(i)
        if a.kind == "Substitution" and a.person in players and a.team in names:
            spelled = norm(a.desc.rpartition(" FOR ")[2])      # the play-by-play's own spelling of who goes out
            if a.person not in names[a.team][spelled]:
                names[a.team][spelled].append(a.person)

    def lookup(team: int, name: str) -> list[int]:
        for table, spelling in ((names, name), (bare_names, bare(name)), (first_names, name)):
            found = table.get(team, {}).get(norm(spelling))
            if found:
                return list(dict.fromkeys(found))
        # teammates who share a family name: "L. James", "Jay. Williams"; the Morris twins: "Mark Morris"
        prefix, dot, family = bare(name).partition(". ")
        if not dot:
            prefix, _, family = bare(name).partition(" ")
        if prefix and family:
            found = [p for p in dict.fromkeys(bare_names.get(team, {}).get(norm(family), []))
                     if first[p].startswith(norm(prefix))]
            if found:
                return found
        # a name since changed: the teammate whose own events are spelled that way ("MISS Kanter 25' 3PT ...")
        return [p for p, v in players.items() if v[0] == team and name and any(
            acts[k].kind != "Substitution" and acts[k].desc.removeprefix("MISS ").startswith(name + " ")
            for k in seen[p])]

    def resolve(i: int, on: set[int]) -> int | None:
        a = acts[i]
        cands = lookup(a.team, incoming(a.desc))
        if len(cands) > 1:
            cands = [p for p in cands if p not in on] or cands
        if len(cands) > 1:
            def next_seen(p: int) -> int:
                k = bisect.bisect_right(seen[p], i)
                return seen[p][k] if k < len(seen[p]) else len(acts)
            cands.sort(key=next_seen)
        return cands[0] if cands else None

    def by_minutes(pids) -> list[int]:
        return sorted(pids, key=lambda p: -players[p][2])

    def openers(team: int, idx: list[int], prev: set[int]) -> set[int]:
        found: list[int] = []
        came_in: set[int] = set()
        for i in idx:
            a = acts[i]
            if a.team != team:
                continue
            if a.kind == "Substitution":
                if a.person and a.person not in came_in and a.person not in found:
                    found.append(a.person)
                inn = resolve(i, set(found) | came_in)
                if inn is not None:
                    came_in.add(inn)
            elif (a.kind not in NOT_ON_FLOOR and a.person in players and players[a.person][0] == team
                  and a.person not in came_in and a.person not in found and "Technical" not in a.sub_type):
                found.append(a.person)
        if len(found) < 5:
            found += by_minutes(p for p in prev if p not in found and p not in came_in)[: 5 - len(found)]
        if len(found) < 5:
            found += by_minutes(p for p, v in players.items()
                                if v[0] == team and v[2] and p not in found and p not in came_in)[: 5 - len(found)]
        return set(found[:5])

    stints: list[dict] = []
    secs: dict[int, float] = defaultdict(float)
    bad = unknown = 0
    score = [0, 0]
    starters = {t: {p for p, v in players.items() if v[0] == t and v[1]} for t in teams}
    prev: dict[int, set[int]] = {t: set() for t in teams}
    for p in sorted({a.period for a in acts if a.period}):
        idx = [i for i, a in enumerate(acts) if a.period == p]
        on = {t: starters[t] if p == 1 and len(starters[t]) == 5 else openers(t, idx, prev[t]) for t in teams}
        on = {t: set(s) for t, s in on.items()}
        cur, opened = period_start(p), list(score)
        count = {t: dict(fga=0, fta=0, oreb=0, tov=0) for t in teams}
        last_miss = None

        def close(until: float) -> None:
            nonlocal cur, opened, count, bad
            if until <= cur:
                return
            h, w = sorted(on[home]), sorted(on[away])
            bad += len(h) != 5 or len(w) != 5
            for pid in h + w:
                secs[pid] += until - cur
            poss = {t: c["fga"] + 0.44 * c["fta"] - c["oreb"] + c["tov"] for t, c in count.items()}
            stints.append(dict(period=p, start_s=cur, end_s=until, home=h, away=w, home_pts=score[0] - opened[0],
                               away_pts=score[1] - opened[1], home_poss=poss[home], away_poss=poss[away]))
            cur, opened = until, list(score)
            count = {t: dict(fga=0, fta=0, oreb=0, tov=0) for t in teams}

        for i in idx:
            a = acts[i]
            left = clock_left(a.clock)
            at = min(max(period_end(p) - left if left is not None else cur, cur), period_end(p))
            if a.kind == "Substitution":
                close(at)
                inn = resolve(i, on.get(a.team, set()))
                unknown += inn is None
                if a.team in on:
                    on[a.team].discard(a.person)
                    if inn is not None:
                        on[a.team].add(inn)
                continue
            if a.score_home is not None:
                score[0] = max(score[0], a.score_home)
            if a.score_away is not None:
                score[1] = max(score[1], a.score_away)
            c = count.get(a.team)
            if c is None:
                continue
            if a.is_fg:
                c["fga"] += 1
                last_miss = None if a.made else a.team
            elif a.kind == "Free Throw":
                c["fta"] += 1
                if last_of_trip(a.sub_type):
                    last_miss = None if a.made else a.team
            elif a.kind == "Turnover":
                c["tov"] += 1
            elif a.kind == "Rebound":
                c["oreb"] += a.team == last_miss
                last_miss = None
        close(period_end(p))
        prev = {t: set(on[t]) for t in teams}
    err = max((abs(secs.get(pid, 0.0) - v[2]) for pid, v in players.items()), default=0.0)
    score_ok = tuple(score) == tuple(final)
    check = dict(stints=len(stints), bad_lineups=bad, unknown_subs=unknown, max_minutes_error_s=round(err, 1),
                 score_ok=score_ok, ok=bool(stints) and bad == 0 and unknown == 0 and err <= TOLERANCE_S and score_ok)
    return stints, check


def build(con: duckdb.DuckDBPyConnection, seasons: set[str] | None = None) -> dict[str, int]:
    """Rebuild stints and stint_checks for every finished game of the given seasons (None: every season with
    play-by-play)."""
    if seasons is None:
        seasons = {s for (s,) in con.execute("select distinct g.season from pbp join games g using (game_id)").fetchall()}
    counts = {"stints": 0, "stint_games": 0, "stint_games_ok": 0}
    for season in sorted(seasons):
        meta = {r[0]: r[1:] for r in con.execute("""
            select game_id, home_id, away_id, home_score, away_score from games where season = ? and status = 3""",
                                                 [season]).fetchall()}
        players: dict[str, dict[int, tuple]] = defaultdict(dict)
        for gid, pid, tid, starter, sec, family, full in con.execute("""
                select pg.game_id, pg.player_id, pg.team_id, pg.starter, pg.seconds, pg.family_name, pg.name
                from player_games pg join games g using (game_id) where g.season = ?""", [season]).fetchall():
            players[gid][pid] = (tid, bool(starter), sec or 0, family or "", full or "")
        acts: dict[str, list[Act]] = defaultdict(list)
        for row in con.execute(f"""select {', '.join('p.' + c.strip() for c in PBP_COLS.split(','))}
                                   from pbp p join games g using (game_id) where g.season = ?
                                   order by p.game_id, p.action_number""", [season]).fetchall():
            acts[row[0]].append(act(row))
        rows, checks = [], []
        for gid, (home, away, hs, as_) in meta.items():
            if gid not in acts or gid not in players:
                continue
            try:
                stints, check = game(home, away, acts[gid], players[gid], (hs, as_))
            except Exception:       # one odd game must not stop the morning run; it is just left out
                log.exception("stints failed for %s", gid)
                stints, check = [], dict(stints=0, bad_lineups=0, unknown_subs=0, max_minutes_error_s=None,
                                         score_ok=False, ok=False)
            checks.append(dict(game_id=gid, **check))
            for k, s in enumerate(stints):
                lineup = (s["home"] + [None] * 5)[:5] + (s["away"] + [None] * 5)[:5]
                rows.append(dict(game_id=gid, idx=k, period=s["period"], start_s=s["start_s"], end_s=s["end_s"],
                                 **dict(zip(["h1", "h2", "h3", "h4", "h5", "a1", "a2", "a3", "a4", "a5"], lineup)),
                                 home_pts=s["home_pts"], away_pts=s["away_pts"], home_poss=s["home_poss"],
                                 away_poss=s["away_poss"]))
        con.execute("delete from stints where game_id in (select game_id from games where season = ?)", [season])
        counts["stints"] += db.upsert(con, "stints", rows)
        db.upsert(con, "stint_checks", checks)
        counts["stint_games"] += len(checks)
        counts["stint_games_ok"] += sum(c["ok"] for c in checks)
    return counts

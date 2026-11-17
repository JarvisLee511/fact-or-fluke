"""ESPN's public scoreboard and game summaries: where the morning run reads last night's games when
stats.nba.com does not answer.

Since 2026-11-11 stats.nba.com serves browsers but leaves every scripted request hanging (the laptop's
own, whatever it sends). We do not dress up as a browser to get past that: each run asks stats.nba.com
once and, when it does not answer, reads ESPN's public JSON instead, saying who it is.

ESPN has the schedule, scores, box scores and play-by-play, but not the tracking data (passes, touches,
catch-and-shoot, closest defender) or the shot chart's zones, so the fun facts built on those keep their
last stats.nba.com numbers until it answers again. Everything is converted into the stats.nba.com shapes
the rest of the pipeline reads, marked "source": "espn", with NBA ids:
- games are matched on (ET date, home, away) in the last stats.nba.com schedule, whose status, score and
  tip time ESPN keeps current (a game made up on another date is found by its teams; an NBA Cup knockout
  game fills that date's open slot);
- players go through an ESPN -> NBA id map (raw/espn/ids) learned from games both sources have and, for a
  player new to it, by name in the league's player index; one neither can place gets ESPN_ID_BASE plus
  his ESPN id.
"""
from __future__ import annotations

import copy
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

from ..config import ET
from ..store import raw
from ..store.load import seconds as _seconds
from ..store.stints import bare, norm
from . import nbastats as ns
from .http import fetch

BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
HEADERS = {"User-Agent": "fact-or-fluke/1.0 (personal, non-commercial)", "Accept": "application/json"}
TRICODE = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}
ESPN_ID_BASE = 900_000_000
PATCH_BACK = 2               # days before the base schedule was taken that are patched again (late finals)
MAKEUP_DAYS = 45             # how far a postponed game may move
OVER = {"STATUS_FINAL", "STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_FORFEIT"}   # nothing more will change
NOT_STARTED = {"STATUS_SCHEDULED", "STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_DELAYED"}
# ESPN play types that are turnovers without saying so, and violations that are not turnovers
TURNOVERS = {"traveling", "double dribble", "discontinued dribble", "palming", "backcourt", "punched ball",
             "offensive goaltending", "illegal assist", "illegal screen", "basket from below", "inbound",
             "excess timeout", "3-second", "5-second", "8-second", "step out of bounds", "out of bounds"}
VIOLATIONS = {"delay of game", "defensive goaltending", "kicked ball", "lane", "double lane", "jump ball"}

log = logging.getLogger(__name__)


def get(path: str, **params) -> dict:
    return json.loads(fetch(f"{BASE}/{path}" + ("?" + urlencode(params) if params else ""), HEADERS))


def tricode(abbreviation: str) -> str:
    return TRICODE.get(abbreviation, abbreviation)


def _utc(s: str) -> datetime:
    """'2026-11-15T18:00Z' -> aware UTC datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def _status(event: dict) -> str:
    return event["competitions"][0]["status"]["type"]["name"]


def scoreboard(d: date) -> dict:
    """One ET date's games: archived, and fetched again until every game on it is over."""
    parts = ("espn", "scoreboard", d.isoformat())
    if raw.exists(*parts):
        sb = raw.load(*parts)
        if all(_status(e) in OVER for e in sb.get("events", [])):
            return sb
    sb = get("scoreboard", dates=d.strftime("%Y%m%d"))
    raw.save(sb, *parts)
    return sb


def summary(event_id: str) -> dict:
    """A finished game's box score and play-by-play (archived: asked for only once a game is over)."""
    parts = ("espn", "summary", str(event_id))
    if raw.exists(*parts):
        return raw.load(*parts)
    sm = get("summary", event=event_id)
    raw.save(sm, *parts)
    return sm


# --- schedule ------------------------------------------------------------------------------------------

def schedule(base: dict, base_day: date, day: date) -> dict:
    """`base` (the stats.nba.com schedule archived on base_day, or an earlier patch of it) with ESPN's status,
    score and tip time for every game from PATCH_BACK days before base_day through `day`."""
    sched = copy.deepcopy(base)
    games = [g for gd in sched["leagueSchedule"]["gameDates"] for g in gd["games"]]
    teams = {side["teamTricode"]: {k: side.get(k) for k in ("teamId", "teamName", "teamCity", "teamTricode",
                                                             "teamSlug")}
             for g in games for side in (g["homeTeam"], g["awayTeam"]) if side.get("teamTricode")}
    d = base_day - timedelta(days=PATCH_BACK)
    while d <= day:
        for e in scoreboard(d).get("events", []):
            g = _match(e, games, teams)
            if g is None:
                log.warning("ESPN game %s (%s) matches no game in the schedule", e.get("id"), e.get("shortName"))
            else:
                _patch(g, e)
        d += timedelta(days=1)
    sched["source"] = "espn"
    return sched


def _sides(competition: dict) -> tuple[dict, dict]:
    by = {c["homeAway"]: c for c in competition["competitors"]}
    return by["home"], by["away"]


def _match(e: dict, games: list[dict], teams: dict) -> dict | None:
    home, away = _sides(e["competitions"][0])
    h, a = tricode(home["team"]["abbreviation"]), tricode(away["team"]["abbreviation"])
    tip = _utc(e["date"])
    day = tip.astimezone(ET).date()
    for g in games:
        if g.get("espnId") == e["id"]:
            return g
    same = [g for g in games if g["homeTeam"].get("teamTricode") == h and g["awayTeam"].get("teamTricode") == a]
    exact = [g for g in same if g["gameDateEst"][:10] == day.isoformat()]
    if exact:
        return exact[0]
    moved = [g for g in same if g["gameStatus"] != 3 and not g.get("espnId")
             and abs((date.fromisoformat(g["gameDateEst"][:10]) - day).days) <= MAKEUP_DAYS]
    if moved:           # a postponed game, made up on another date: the nearest one between these two teams
        return min(moved, key=lambda g: abs((date.fromisoformat(g["gameDateEst"][:10]) - day).days))
    open_slots = [g for g in games if g["gameDateEst"][:10] == day.isoformat() and not g["homeTeam"].get("teamTricode")
                  and not g.get("espnId")]
    if open_slots and h in teams and a in teams:     # an NBA Cup knockout game the schedule still lists as TBD
        g = min(open_slots, key=lambda g: abs((_utc(g["gameDateTimeUTC"]) - tip).total_seconds()))
        g["homeTeam"].update(teams[h])
        g["awayTeam"].update(teams[a])
        return g
    return None


def _patch(g: dict, e: dict) -> None:
    c = e["competitions"][0]
    home, away = _sides(c)
    status = _status(e)
    tip = _utc(e["date"])
    g["espnId"] = e["id"]
    g["gameDateTimeUTC"] = tip.strftime("%Y-%m-%dT%H:%M:%SZ")
    g["gameDateEst"] = f"{tip.astimezone(ET).date().isoformat()}T00:00:00Z"
    g["gameStatus"] = 3 if status == "STATUS_FINAL" else 1 if status in NOT_STARTED else 2
    g["gameStatusText"] = c["status"]["type"].get("shortDetail", "")
    g["postponedStatus"] = "Y" if status in ("STATUS_POSTPONED", "STATUS_CANCELED") else "N"
    if g["gameStatus"] > 1:
        g["homeTeam"]["score"] = int(home.get("score") or 0)
        g["awayTeam"]["score"] = int(away.get("score") or 0)


# --- players -------------------------------------------------------------------------------------------

def _newest_index():
    files = [f for s in sorted(p.name for p in raw.RAW.joinpath("players").glob("*") if p.is_dir())
             for f in raw.files("players", s)]
    return max(files, key=lambda p: (p.parent.name, p.name)) if files else None


def player_index() -> list[dict]:
    """The newest archived league player index (every player ever, with his team as of that day)."""
    newest = _newest_index()
    return ns.result_sets(raw.read(newest)).get("PlayerIndex", []) if newest else []


def _height(h: str | None) -> str:
    """ESPN's 6' 9\" -> the index's '6-9'."""
    m = re.match(r"\s*(\d+)'\s*(\d+)", h or "")
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def rosters(ids: Ids, teams: dict[str, int]) -> dict:
    """The newest player index with today's rosters from ESPN's team pages: a player on one is on that team,
    a player on none is on no team, and a player the index has never seen is added. `teams`: {tricode: NBA
    team id}. Same shape as stats.nba.com's playerindex, marked "source": "espn"."""
    base = raw.read(_newest_index())
    sets = base["resultSets"] if isinstance(base["resultSets"], list) else [base["resultSets"]]
    rs = next(s for s in sets if s["name"] == "PlayerIndex")
    headers = rs["headers"]
    rows = {r[headers.index("PERSON_ID")]: dict(zip(headers, r)) for r in rs["rowSet"]}
    seen: dict[int, tuple[int, str]] = {}
    for t in get("teams")["sports"][0]["leagues"][0]["teams"]:
        code = tricode(t["team"]["abbreviation"])
        tid = teams[code]
        for a in get(f"teams/{t['team']['id']}/roster").get("athletes", []):
            pid = ids.resolve(int(a["id"]), a["displayName"], tid)
            seen[pid] = (tid, code)
            if pid not in rows:
                first, family = _split(a["displayName"])
                rows[pid] = {**dict.fromkeys(headers), "PERSON_ID": pid, "PLAYER_FIRST_NAME": first,
                             "PLAYER_LAST_NAME": family, "POSITION": (a.get("position") or {}).get("abbreviation", ""),
                             "HEIGHT": _height(a.get("displayHeight"))}
    for pid, r in rows.items():
        tid, code = seen.get(pid, (None, None))
        if tid:
            r.update(TEAM_ID=tid, TEAM_ABBREVIATION=code, ROSTER_STATUS=1)
        elif r.get("ROSTER_STATUS") == 1:
            r.update(ROSTER_STATUS=0)
    ids.save()
    return {"source": "espn", "resultSets": [{"name": "PlayerIndex", "headers": headers,
                                              "rowSet": [[r.get(h) for h in headers] for r in rows.values()]}]}


@dataclass
class Who:
    pid: int
    team: int
    first: str
    family: str

    @property
    def full(self) -> str:
        return f"{self.first} {self.family}".strip()


def _split(display: str) -> tuple[str, str]:
    first, _, family = display.strip().partition(" ")
    return first, family


class Ids:
    """ESPN athlete id -> NBA person id, archived at raw/espn/ids."""

    def __init__(self, index: list[dict]):
        self.map: dict[int, int] = ({int(k): int(v) for k, v in raw.load("espn", "ids").items()}
                                    if raw.exists("espn", "ids") else {})
        self.index = index
        self.by_id = {r["PERSON_ID"]: r for r in index}
        self.dirty = False

    def save(self) -> None:
        if self.dirty:
            raw.save({str(k): v for k, v in sorted(self.map.items())}, "espn", "ids")
            self.dirty = False

    def _add(self, espn_id: int, pid: int) -> None:
        if self.map.get(espn_id) not in (None, pid):
            log.warning("ESPN athlete %s was NBA %s, now %s", espn_id, self.map[espn_id], pid)
        if self.map.get(espn_id) != pid:
            self.map[espn_id] = pid
            self.dirty = True

    def by_name(self, name: str, team_id: int | None) -> int | None:
        """The index player with this name: the only one, else the one on this team (or on a roster); then
        without a Jr./III; then a teammate with the same family name and initial ("Nic" = Nicolas Claxton), or
        the only teammate with that family name ("Bub" = Carlton Carrington)."""
        def full(r):
            return f'{r["PLAYER_FIRST_NAME"]} {r["PLAYER_LAST_NAME"]}'.strip()

        def pick(rows):
            if len(rows) > 1:
                rows = [r for r in rows if r.get("TEAM_ID") == team_id] or [r for r in rows
                                                                          if r.get("ROSTER_STATUS") == 1]
            return rows[0]["PERSON_ID"] if len(rows) == 1 else None

        found = pick([r for r in self.index if norm(full(r)) == norm(name)])
        if found is None:
            found = pick([r for r in self.index if norm(bare(full(r))) == norm(bare(name))])
        if found is None and team_id:
            first, family = _split(name)
            mates = [r for r in self.index if r.get("TEAM_ID") == team_id
                     and norm(bare(r["PLAYER_LAST_NAME"])) == norm(bare(family))]
            initial = [r for r in mates if norm(r["PLAYER_FIRST_NAME"])[:1] == norm(first)[:1]]
            found = pick(initial) if initial else pick(mates)
        return found

    def resolve(self, espn_id: int, name: str, team_id: int | None) -> int:
        if espn_id in self.map:
            return self.map[espn_id]
        pid = self.by_name(name, team_id)
        if pid is None:
            log.warning("ESPN athlete %s (%s) is not in the player index: id %s", espn_id, name,
                        ESPN_ID_BASE + espn_id)
            return ESPN_ID_BASE + espn_id
        self._add(espn_id, pid)
        return pid

    def who(self, espn_id: int, display: str, team_id: int) -> Who:
        pid = self.resolve(espn_id, display, team_id)
        r = self.by_id.get(pid)
        first, family = (r["PLAYER_FIRST_NAME"], r["PLAYER_LAST_NAME"]) if r else _split(display)
        return Who(pid, team_id, first, family)

    def learn(self, nba_box: dict, sm: dict) -> int:
        """Pair the ESPN athletes of a game stats.nba.com also has with its players: same team, then the same
        name, else the same minutes, points and shots (one candidate only). -> pairs learned."""
        b = nba_box["boxScoreTraditional"]
        sides = {b[s]["teamTricode"]: b[s] for s in ("homeTeam", "awayTeam")}
        n = 0
        for block in sm.get("boxscore", {}).get("players", []):
            side = sides.get(tricode(block["team"]["abbreviation"]))
            if side is None or not block.get("statistics"):
                continue
            nba = {p["personId"]: p for p in side["players"]}
            taken: set[int] = set()
            keys = block["statistics"][0]["keys"]
            later = []
            for a in block["statistics"][0]["athletes"]:
                eid, name = int(a["athlete"]["id"]), a["athlete"]["displayName"]
                hit = [pid for pid, p in nba.items() if norm(f'{p["firstName"]} {p["familyName"]}') == norm(name)]
                if len(hit) == 1:
                    self._add(eid, hit[0])
                    taken.add(hit[0])
                    n += 1
                else:
                    later.append((eid, name, dict(zip(keys, a.get("stats") or []))))
            for eid, name, st in later:
                if not st:
                    continue
                mins, pts = _num(st.get("minutes")), _num(st.get("points"))
                fga = _made(st.get("fieldGoalsMade-fieldGoalsAttempted"))[1]
                hit = [pid for pid, p in nba.items() if pid not in taken
                       and p["statistics"].get("points") == pts
                       and p["statistics"].get("fieldGoalsAttempted") == fga
                       and abs(round(_seconds(p["statistics"].get("minutes")) / 60) - mins) <= 1]
                if len(hit) == 1:
                    self._add(eid, hit[0])
                    taken.add(hit[0])
                    n += 1
                else:
                    log.warning("could not pair ESPN athlete %s (%s) in game %s", eid, name, b["gameId"])
        return n


def _num(v) -> int:
    if v in (None, "", "--"):
        return 0
    return int(float(str(v).replace("+", "")))


def _made(v) -> tuple[int, int]:
    made, _, tried = str(v or "0-0").partition("-")
    return _num(made), _num(tried)


# --- box score and play-by-play ------------------------------------------------------------------------

def to_box(sm: dict, g: dict, ids: Ids) -> tuple[dict, dict[int, Who]]:
    """ESPN summary -> boxscoretraditionalv3 shape, and who each ESPN athlete is."""
    sides = {g[s]["teamTricode"]: s for s in ("homeTeam", "awayTeam")}
    out = {s: {"teamId": g[s]["teamId"], "teamTricode": g[s]["teamTricode"], "players": []}
           for s in ("homeTeam", "awayTeam")}
    who: dict[int, Who] = {}
    for block in sm["boxscore"]["players"]:
        side = sides[tricode(block["team"]["abbreviation"])]
        tid = g[side]["teamId"]
        if not block.get("statistics"):
            continue
        keys = block["statistics"][0]["keys"]
        for a in block["statistics"][0]["athletes"]:
            ath = a["athlete"]
            w = ids.who(int(ath["id"]), ath["displayName"], tid)
            who[int(ath["id"])] = w
            st = dict(zip(keys, a.get("stats") or []))
            played = bool(st) and not a.get("didNotPlay")
            fgm, fga = _made(st.get("fieldGoalsMade-fieldGoalsAttempted"))
            fg3m, fg3a = _made(st.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
            ftm, fta = _made(st.get("freeThrowsMade-freeThrowsAttempted"))
            position = ((ath.get("position") or {}).get("abbreviation") or "F") if a.get("starter") else ""
            out[side]["players"].append(dict(
                personId=w.pid, firstName=w.first, familyName=w.family, position=position,
                espnId=int(ath["id"]), statistics=dict(
                    minutes=f"PT{_num(st.get('minutes')):02d}M00.00S" if played else "",
                    points=_num(st.get("points")), fieldGoalsMade=fgm, fieldGoalsAttempted=fga,
                    threePointersMade=fg3m, threePointersAttempted=fg3a, freeThrowsMade=ftm,
                    freeThrowsAttempted=fta, reboundsOffensive=_num(st.get("offensiveRebounds")),
                    reboundsDefensive=_num(st.get("defensiveRebounds")), reboundsTotal=_num(st.get("rebounds")),
                    assists=_num(st.get("assists")), steals=_num(st.get("steals")), blocks=_num(st.get("blocks")),
                    turnovers=_num(st.get("turnovers")), foulsPersonal=_num(st.get("fouls")),
                    plusMinusPoints=_num(st.get("plusMinus")))))
    return {"source": "espn", "espnId": g.get("espnId"),
            "boxScoreTraditional": {"gameId": g["gameId"], **out}}, who


def _left(v: str) -> float:
    """'11:37' -> 697.0, '43.9' -> 43.9 seconds left in the period."""
    m, _, s = v.partition(":") if ":" in v else ("0", "", v)
    return int(m or 0) * 60 + float(s or 0)


def _clock(v: str) -> str:
    """'11:37' -> 'PT11M37.00S', '43.9' -> 'PT00M43.90S'."""
    left = _left(v)
    return f"PT{int(left // 60):02d}M{left % 60:05.2f}S"


def _coords(c: dict | None) -> tuple[float, float] | None:
    """ESPN's shot spot: feet across the court (basket at 25) and out from the basket; junk off the floor."""
    if not c or not (0 <= c.get("x", -1) <= 50 and -5 <= c.get("y", -99) <= 94):
        return None
    return float(c["x"]), float(c["y"])


def to_pbp(sm: dict, g: dict, who: dict[int, Who], ids: Ids) -> dict:
    """ESPN summary -> playbyplayv3 shape. Conventions copied from stats.nba.com: a substitution is the player
    going out with 'SUB: <in> FOR <out>'; team rebounds, turnovers and timeouts have team 0 and the team in
    the person field; a missed end-of-quarter heave is nobody's field goal attempt; free throws are
    'Free Throw 1 of 2' with 'MISS' in a miss's description.

    Plays are put in game-clock order (ESPN lists a late-entered play where it was entered) and numbered in
    that order, and the score is counted from the scoring plays: ESPN's own running score is sometimes
    stale or off on single plays and even at the end (130-105 in a game that ended 127-105), while its
    scoring plays add up to the final score and to every player's points."""
    teams = {}
    for c in sm["header"]["competitions"][0]["competitors"]:
        side = "homeTeam" if c["homeAway"] == "home" else "awayTeam"
        teams[str(c["team"]["id"])] = (g[side]["teamId"], "h" if side == "homeTeam" else "v",
                                       c["team"].get("name") or g[side].get("teamName") or "")
    loc = {tid: side for tid, side, _ in teams.values()}
    actions = []
    score = {"h": 0, "v": 0}
    plays = sorted(sm.get("plays", []), key=lambda p: (p["period"]["number"], -_left(p["clock"]["displayValue"]),
                                                      int(p["sequenceNumber"])))
    for n, p in enumerate(plays, 1):
        play_team, play_side, team_name = teams.get(str((p.get("team") or {}).get("id")), (0, "", ""))
        if p.get("scoringPlay") and play_side:
            score[play_side] += int(p.get("scoreValue") or 0)
        parts = []
        for x in p.get("participants", []):
            eid = int(x["athlete"]["id"])
            if eid not in who:          # in the play but not the box score: should not happen
                pid = ids.map.get(eid, ESPN_ID_BASE + eid)
                who[eid] = Who(pid, play_team, "", str(pid))
            parts.append(who[eid])
        first = parts[0] if parts else None
        kind = " ".join(p["type"]["text"].split())
        k = kind.lower()
        text = " ".join((p.get("text") or "").split())
        made = bool(p.get("scoringPlay"))
        tried = p.get("pointsAttempted") or 0
        team_id = first.team if first else play_team
        a = dict(actionNumber=n, actionId=int(p["sequenceNumber"]), period=p["period"]["number"],
                 clock=_clock(p["clock"]["displayValue"]), teamId=team_id, personId=first.pid if first else 0,
                 actionType="", subType="", description=text, isFieldGoal=0, shotResult="", shotValue=0,
                 shotDistance=0.0, xLegacy=0.0, yLegacy=0.0, scoreHome=score["h"], scoreAway=score["v"],
                 location=loc.get(team_id, ""))
        team_event = dict(teamId=0, personId=play_team, location=loc.get(play_team, ""))
        if k.startswith("free throw") or (p.get("shootingPlay") and tried == 1):
            sub = "Free Throw " + kind.split(" - ", 1)[1] if " - " in kind else kind
            made = made or " makes " in f" {text} "
            a.update(actionType="Free Throw", subType=sub,
                     description=f"{'' if made else 'MISS '}{first.family if first else ''} {sub}".strip())
        elif p.get("shootingPlay") and tried in (2, 3):
            if "heave" in k and not made:
                a.update(actionType="Heave", subType="Team Field Goal Attempt", description=f"{team_name} Heave",
                         teamId=0, personId=0, location=loc.get(play_team, ""))
            else:
                spot = _coords(p.get("coordinate"))
                said = re.search(r"(\d+)-foot", text)
                dist = float(said.group(1)) if said else round(math.hypot(spot[0] - 25, spot[1])) if spot else 0.0
                a.update(actionType="Made Shot" if made else "Missed Shot", subType=kind, isFieldGoal=1,
                         shotResult="Made" if made else "Missed", shotValue=tried, shotDistance=dist,
                         xLegacy=(spot[0] - 25) * 10 if spot else 0.0, yLegacy=spot[1] * 10 if spot else 0.0,
                         description=f"{'' if made else 'MISS '}{first.family if first else ''} {dist:g}' "
                                     f"{'3PT ' if tried == 3 else ''}{kind}")
        elif "rebound" in k:
            a.update(actionType="Rebound", subType="Unknown")
            if not first:
                a.update(description=f"{team_name} Rebound", **team_event)
        elif "turnover" in k or k in TURNOVERS:
            a.update(actionType="Turnover", subType=kind.removesuffix(" Turnover"))
            if not first:
                a.update(description=f"{team_name} Turnover: {kind}", **team_event)
        elif k == "substitution" and len(parts) >= 2:
            inn, out = parts[0], parts[1]
            a.update(actionType="Substitution", teamId=out.team, personId=out.pid, location=loc.get(out.team, ""),
                     description=f"SUB: {inn.full} FOR {out.full}")
        elif "foul" in k or "technical" in k or "techfoul" in k or "charge" in k:
            sub = re.sub(r"\s*\bfoul\b", "", kind, flags=re.I).strip()
            a.update(actionType="Foul", subType="Technical" if "tech" in k and "Technical" not in sub else sub)
            if not first:
                a.update(**team_event)
        elif "timeout" in k:
            a.update(actionType="Timeout", subType="Regular", description=f"{team_name} Timeout", **team_event)
        elif k in ("jumpball", "jump ball"):
            a.update(actionType="Jump Ball")
        elif k.startswith(("end ", "start ")):
            a.update(actionType="period", subType=k.split()[0], teamId=0, personId=0, location="")
        elif "challenge" in k or "review" in k or "replay" in k:
            a.update(actionType="Instant Replay", teamId=0, personId=0)
        elif "ejection" in k:
            a.update(actionType="Ejection")
        elif "violation" in k or k in VIOLATIONS:
            a.update(actionType="Violation", subType=kind.removesuffix(" Violation"))
            if not first:
                a.update(**team_event)
        actions.append(a)
    return {"source": "espn", "espnId": g.get("espnId"), "game": {"gameId": g["gameId"], "actions": actions}}


def game(g: dict, season: str, ids: Ids) -> None:
    """Archive one finished game (schedule entry with its espnId) as stats.nba.com box score and play-by-play."""
    sm = summary(g["espnId"])
    box, who = to_box(sm, g, ids)
    pbp = to_pbp(sm, g, who, ids)
    raw.save(box, "games", season, "box", g["gameId"])
    raw.save(pbp, "games", season, "pbp", g["gameId"])

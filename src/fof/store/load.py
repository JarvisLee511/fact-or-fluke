"""Raw payloads -> table rows. Pure functions (payload in, list of dicts out); db.upsert writes them."""
from __future__ import annotations

import json
import re

from ..ingest import nbastats as ns

SEASON_TYPE = {"001": "Preseason", "002": "Regular Season", "003": "All-Star", "004": "Playoffs",
               "005": "PlayIn", "006": "Cup Final"}


def season_type(game_id: str) -> str:
    return SEASON_TYPE.get(game_id[:3], "Other")


def seconds(minutes: str | None) -> int:
    """'36:38' or 'PT36M38.00S' -> 2198."""
    if not minutes:
        return 0
    m = re.fullmatch(r"PT(?:(\d+)M)?(?:([\d.]+)S)?", minutes)
    if m:
        return int(m.group(1) or 0) * 60 + round(float(m.group(2) or 0))
    mins, _, secs = minutes.partition(":")
    return int(mins or 0) * 60 + round(float(secs or 0))


def _int(v) -> int | None:
    return None if v in (None, "") else int(float(v))


def schedule_rows(payload: dict, season: str) -> list[dict]:
    rows = []
    for gd in payload["leagueSchedule"]["gameDates"]:
        for g in gd["games"]:
            h, a = g["homeTeam"], g["awayTeam"]
            rows.append(dict(
                game_id=g["gameId"], season=season, season_type=season_type(g["gameId"]),
                game_date=g["gameDateEst"][:10], tip_utc=g["gameDateTimeUTC"].rstrip("Z") or None,
                home_id=h["teamId"], away_id=a["teamId"], home_code=h.get("teamTricode") or "",
                away_code=a.get("teamTricode") or "", home_score=_int(h.get("score")), away_score=_int(a.get("score")),
                status=g["gameStatus"], arena_city=g.get("arenaCity") or "", arena_state=g.get("arenaState") or "",
                neutral=bool(g.get("isNeutral")), label=g.get("gameLabel") or "", subtype=g.get("gameSubtype") or ""))
    return rows


def box_rows(payload: dict) -> list[dict]:
    b = payload["boxScoreTraditional"]
    rows = []
    for side in ("homeTeam", "awayTeam"):
        t = b[side]
        for p in t["players"]:
            s = p["statistics"]
            rows.append(dict(
                game_id=b["gameId"], player_id=p["personId"], team_id=t["teamId"], team_code=t["teamTricode"],
                name=f'{p["firstName"]} {p["familyName"]}'.strip(), family_name=p["familyName"],
                position=p.get("position") or "",
                starter=bool(p.get("position")), dnp=not s.get("minutes"), seconds=seconds(s.get("minutes")),
                pts=s["points"], fgm=s["fieldGoalsMade"], fga=s["fieldGoalsAttempted"], fg3m=s["threePointersMade"],
                fg3a=s["threePointersAttempted"], ftm=s["freeThrowsMade"], fta=s["freeThrowsAttempted"],
                oreb=s["reboundsOffensive"], dreb=s["reboundsDefensive"], reb=s["reboundsTotal"], ast=s["assists"],
                stl=s["steals"], blk=s["blocks"], tov=s["turnovers"], pf=s["foulsPersonal"],
                plus_minus=_int(s.get("plusMinusPoints")) or 0))
    return rows


def pbp_rows(payload: dict) -> list[dict]:
    g = payload["game"]
    return [dict(
        game_id=g["gameId"], action_number=a["actionNumber"], period=a["period"], clock=a["clock"],
        team_id=a.get("teamId") or 0, person_id=a.get("personId") or 0, action_type=a.get("actionType") or "",
        sub_type=a.get("subType") or "", description=a.get("description") or "", is_fg=bool(a.get("isFieldGoal")),
        shot_result=a.get("shotResult") or "", shot_value=_int(a.get("shotValue")) or 0,
        shot_distance=a.get("shotDistance") or 0.0, x=a.get("xLegacy") or 0.0, y=a.get("yLegacy") or 0.0,
        score_home=_int(a.get("scoreHome")), score_away=_int(a.get("scoreAway")), location=a.get("location") or "",
        video=bool(a.get("videoAvailable")), action_id=a.get("actionId") or 0) for a in g["actions"]]


def shot_rows(payload: dict, season: str, season_type_: str) -> list[dict]:
    return [dict(
        game_id=r["GAME_ID"], event_id=r["GAME_EVENT_ID"], player_id=r["PLAYER_ID"], team_id=r["TEAM_ID"],
        game_date=f'{r["GAME_DATE"][:4]}-{r["GAME_DATE"][4:6]}-{r["GAME_DATE"][6:]}', season=season,
        season_type=season_type_, period=r["PERIOD"], action_type=r["ACTION_TYPE"], shot_type=r["SHOT_TYPE"],
        zone_basic=r["SHOT_ZONE_BASIC"], zone_area=r["SHOT_ZONE_AREA"], zone_range=r["SHOT_ZONE_RANGE"],
        distance=r["SHOT_DISTANCE"], loc_x=r["LOC_X"], loc_y=r["LOC_Y"], made=bool(r["SHOT_MADE_FLAG"]))
        for r in ns.result_sets(payload)["Shot_Chart_Detail"]]


def dash_rows(payload: dict, season: str, as_of: str, measure: str) -> list[dict]:
    rows = next(iter(ns.result_sets(payload).values()), [])
    return [dict(season=season, as_of=as_of, measure=measure, player_id=r["PLAYER_ID"],
                 team_code=r.get("TEAM_ABBREVIATION") or r.get("PLAYER_LAST_TEAM_ABBREVIATION") or "",
                 data=json.dumps(r)) for r in rows]


def pass_rows(payload: dict, season: str, as_of: str) -> list[dict]:
    return [dict(season=season, as_of=as_of, player_id=r["PLAYER_ID"], passer_id=r["PASS_TEAMMATE_PLAYER_ID"],
                 passer_name=r["PASS_FROM"], passes=_int(r["PASS"]), ast=_int(r["AST"]), fgm=_int(r["FGM"]),
                 fga=_int(r["FGA"]), fg3m=_int(r["FG3M"]), fg3a=_int(r["FG3A"]))
            for r in ns.result_sets(payload).get("PassesReceived", [])]


def player_rows(payload: dict) -> list[dict]:
    return [dict(player_id=r["PERSON_ID"], name=f'{r["PLAYER_FIRST_NAME"]} {r["PLAYER_LAST_NAME"]}'.strip(),
                 team_code=r.get("TEAM_ABBREVIATION") or "", position=r.get("POSITION") or "",
                 height=r.get("HEIGHT") or "") for r in ns.result_sets(payload)["PlayerIndex"]]

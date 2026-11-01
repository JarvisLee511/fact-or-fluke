"""Thin client for stats.nba.com, the endpoints behind nba.com's own stats pages."""
from __future__ import annotations

import json
from urllib.parse import urlencode

from .http import fetch

STATS_HEADERS = {
    "Referer": "https://www.nba.com/",
    "Origin": "https://www.nba.com",
    "x-nba-stats-origin": "stats",
    "x-nba-stats-token": "true",
}


def get_json(endpoint: str, **params) -> dict:
    url = f"https://stats.nba.com/stats/{endpoint}?" + urlencode(params)
    return json.loads(fetch(url, STATS_HEADERS))


def result_sets(payload: dict) -> dict[str, list[dict]]:
    """Flatten the classic {resultSets: [{name, headers, rowSet}]} shape into {name: [row dicts]}."""
    sets = payload.get("resultSets") or payload.get("resultSet") or []
    if isinstance(sets, dict):
        sets = [sets]
    return {s["name"]: [dict(zip(s["headers"], row)) for row in s["rowSet"]] for s in sets}


LEAGUE_DASH_DEFAULTS = dict(
    College="", Conference="", Country="", DateFrom="", DateTo="", Division="", DraftPick="",
    DraftYear="", GameScope="", Height="", LastNGames=0, LeagueID="00", Location="", Month=0,
    OpponentTeamID=0, Outcome="", PORound=0, PerMode="Totals", PlayerExperience="",
    PlayerOrTeam="Player", PlayerPosition="", SeasonSegment="", SeasonType="Regular Season",
    StarterBench="", TeamID=0, VsConference="", VsDivision="", Weight="",
)

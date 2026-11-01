"""Fetchers: stats.nba.com -> raw archive. Each returns the payload and skips the network when the
archived file already exists, unless refresh=True (used for documents that change during the season)."""
from __future__ import annotations

from datetime import date

from ..store import raw
from . import nbastats as ns

GAME_ENDPOINTS = {
    "box": ("boxscoretraditionalv3", dict(LeagueID="00", StartPeriod=0, EndPeriod=0, StartRange=0, EndRange=0,
                                          RangeType=0)),
    "pbp": ("playbyplayv3", dict(StartPeriod=0, EndPeriod=0)),
}
TRACKING = ["ElbowTouch", "PostTouch", "PaintTouch", "Drives", "CatchShoot", "PullUpShot", "Passing"]
CLOSE_DEF = {"0-2": "0-2 Feet - Very Tight", "2-4": "2-4 Feet - Tight", "4-6": "4-6 Feet - Open",
             "6+": "6+ Feet - Wide Open"}
PTSHOT_EXTRA = dict(DribbleRange="", GameSegment="", GeneralRange="", PaceAdjust="N", Period=0, PlusMinus="N",
                    Rank="N", ShotClockRange="", ShotDistRange="", TouchTimeRange="")
SHOTCHART_BASE = dict(ContextMeasure="FGA", LastNGames=0, LeagueID="00", Month=0, OpponentTeamID=0, Period=0,
                      PlayerID=0, TeamID=0, PlayerPosition="", RookieYear="", GameSegment="", Location="", Outcome="",
                      SeasonSegment="", VsConference="", VsDivision="", ClutchTime="", AheadBehind="", PointDiff="",
                      RangeType="", StartPeriod="", EndPeriod="", StartRange="", EndRange="", ContextFilter="",
                      GameID="", PORound="")
PASS_BASE = dict(DateFrom="", DateTo="", GameSegment="", LastNGames=0, LeagueID="00", Location="", Month=0,
                 OpponentTeamID=0, Outcome="", PerMode="Totals", Period=0, SeasonSegment="", VsConference="",
                 VsDivision="")


def _cached(parts: tuple[str, ...], fetch, refresh: bool = False):
    if not refresh and raw.exists(*parts):
        return raw.load(*parts)
    payload = fetch()
    raw.save(payload, *parts)
    return payload


def schedule(season: str, as_of: date, refresh: bool = True) -> dict:
    return _cached(("schedule", season, as_of.isoformat()),
                   lambda: ns.get_json("scheduleleaguev2", LeagueID="00", Season=season), refresh)


def game(kind: str, game_id: str, season: str) -> dict:
    endpoint, params = GAME_ENDPOINTS[kind]
    return _cached(("games", season, kind, game_id), lambda: ns.get_json(endpoint, GameID=game_id, **params))


def shots(season: str, season_type: str, d_from: date, d_to: date, refresh: bool = False) -> dict:
    tag = f"{season_type.replace(' ', '')}_{d_from:%Y%m%d}_{d_to:%Y%m%d}"
    return _cached(("shots", season, tag), lambda: ns.get_json(
        "shotchartdetail", **SHOTCHART_BASE, Season=season, SeasonType=season_type,
        DateFrom=d_from.strftime("%m/%d/%Y"), DateTo=d_to.strftime("%m/%d/%Y")), refresh)


def dashboards(season: str, as_of: date, season_type: str = "Regular Season", refresh: bool = False) -> dict:
    """Season-to-date tracking dashboards: {measure: payload}."""
    out = {}
    base = {**ns.LEAGUE_DASH_DEFAULTS, "Season": season, "SeasonType": season_type}
    for m in TRACKING:
        out[m] = _cached(("dash", season, as_of.isoformat(), m),
                         lambda m=m: ns.get_json("leaguedashptstats", **base, PtMeasureType=m), refresh)
    for key, label in CLOSE_DEF.items():
        out[f"CloseDef_{key}"] = _cached(("dash", season, as_of.isoformat(), f"CloseDef_{key}"),
                                         lambda label=label: ns.get_json("leaguedashplayerptshot", **base,
                                                                         **PTSHOT_EXTRA, CloseDefDistRange=label),
                                         refresh)
    return out


def passes(season: str, as_of: date, player_id: int, team_id: int, season_type: str = "Regular Season",
           refresh: bool = False) -> dict:
    return _cached(("passes", season, as_of.isoformat(), str(player_id)), lambda: ns.get_json(
        "playerdashptpass", **PASS_BASE, PlayerID=player_id, TeamID=team_id, Season=season,
        SeasonType=season_type), refresh)


def player_index(season: str, as_of: date, refresh: bool = True) -> dict:
    return _cached(("players", season, as_of.isoformat()), lambda: ns.get_json(
        "playerindex", LeagueID="00", Season=season, Historical=1, Active="", AllStar="", College="", Country="",
        DraftPick="", DraftRound="", DraftYear="", Height="", TeamID=0, Weight=""), refresh)

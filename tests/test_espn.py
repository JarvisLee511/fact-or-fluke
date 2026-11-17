from datetime import date

from fof.ingest import espn
from fof.store import load, raw, stints

ATL, LAL = 1610612737, 1610612747
GAME = {"gameId": "0022600203", "espnId": "401909952", "gameDateEst": "2026-11-09T00:00:00Z",
        "homeTeam": {"teamId": ATL, "teamTricode": "ATL", "teamName": "Hawks", "score": 0},
        "awayTeam": {"teamId": LAL, "teamTricode": "LAL", "teamName": "Lakers", "score": 0}}
INDEX = [
    dict(PERSON_ID=1630168, PLAYER_FIRST_NAME="Onyeka", PLAYER_LAST_NAME="Okongwu", TEAM_ID=ATL, ROSTER_STATUS=1),
    dict(PERSON_ID=1643412, PLAYER_FIRST_NAME="Kingston", PLAYER_LAST_NAME="Flemings", TEAM_ID=ATL, ROSTER_STATUS=1),
    dict(PERSON_ID=1629029, PLAYER_FIRST_NAME="Luka", PLAYER_LAST_NAME="Dončić", TEAM_ID=LAL, ROSTER_STATUS=1),
    dict(PERSON_ID=1629652, PLAYER_FIRST_NAME="Luguentz", PLAYER_LAST_NAME="Dort", TEAM_ID=ATL, ROSTER_STATUS=1),
    dict(PERSON_ID=1629638, PLAYER_FIRST_NAME="Nickeil", PLAYER_LAST_NAME="Alexander-Walker", TEAM_ID=ATL,
         ROSTER_STATUS=1),
]
KEYS = ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
        "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "freeThrowsMade-freeThrowsAttempted", "rebounds",
        "assists", "turnovers", "steals", "blocks", "offensiveRebounds", "defensiveRebounds", "fouls", "plusMinus"]


def athlete(eid, name, stats, starter=False, position="G"):
    return {"athlete": {"id": str(eid), "displayName": name, "position": {"abbreviation": position}},
            "starter": starter, "didNotPlay": not stats, "stats": stats}


def play(seq, kind, text, team=None, parts=(), clock="11:37", period=1, home=0, away=0, scoring=False,
         shooting=False, tried=0, coordinate=None):
    p = {"sequenceNumber": str(seq), "type": {"text": kind}, "text": text, "period": {"number": period},
         "clock": {"displayValue": clock}, "homeScore": home, "awayScore": away, "scoringPlay": scoring,
         "scoreValue": tried if scoring else 0, "shootingPlay": shooting, "pointsAttempted": tried,
         "participants": [{"athlete": {"id": str(e)}} for e in parts]}
    if team:
        p["team"] = {"id": team}
    if coordinate:
        p["coordinate"] = coordinate
    return p


SUMMARY = {
    "header": {"competitions": [{"competitors": [
        {"homeAway": "home", "team": {"id": "1", "abbreviation": "ATL", "name": "Hawks"}},
        {"homeAway": "away", "team": {"id": "13", "abbreviation": "LAL", "name": "Lakers"}}]}]},
    "boxscore": {"players": [
        {"team": {"abbreviation": "ATL"}, "statistics": [{"keys": KEYS, "athletes": [
            athlete(4431680, "Onyeka Okongwu", ["30", "16", "6-9", "3-4", "1-2", "11", "2", "1", "0", "1", "2", "9",
                                                "3", "-4"], starter=True, position="C"),
            athlete(5149077, "Kingston Flemings", ["24", "8", "3-7", "0-2", "2-2", "2", "6", "2", "2", "0", "0", "2",
                                                   "1", "+3"], starter=True),
            athlete(4397020, "Luguentz Dort", ["18", "4", "1-3", "1-2", "1-1", "3", "0", "0", "1", "0", "1", "2",
                                               "2", "-1"]),
            athlete(4278039, "Nickeil Alexander-Walker", [])]}]},
        {"team": {"abbreviation": "LAL"}, "statistics": [{"keys": KEYS, "athletes": [
            athlete(3945274, "Luka Doncic", ["39", "31", "11-24", "4-11", "5-6", "8", "9", "5", "1", "0", "1", "7",
                                             "2", "+10"], starter=True)]}]}]},
    "plays": [
        play(4, "Jumpball", "Walker Kessler vs. Onyeka Okongwu (Luka Doncic gains possession)", "13",
             (4431680, 3945274), clock="12:00"),
        play(9, "Running Jump Shot", "Onyeka Okongwu makes 24-foot running jump shot (Kingston Flemings assists)",
             "1", (4431680, 5149077), "11:30", home=3, scoring=True, shooting=True, tried=3,
             coordinate={"x": 27, "y": 25}),
        play(30, "Shooting Foul", "Luka Doncic shooting foul", "13", (3945274,), "9:05", home=3),
        play(32, "Free Throw - 1 of 2", "Onyeka Okongwu misses free throw 1 of 2", "1", (4431680,), "9:05",
             home=3, shooting=True, tried=1),
        play(33, "Offensive Rebound", "Hawks offensive team rebound", "1", (), "9:05", home=3),
        play(34, "Free Throw - 2 of 2", "Onyeka Okongwu makes free throw 2 of 2", "1", (4431680,), "9:05",
             home=4, scoring=True, shooting=True, tried=1),
        play(40, "Substitution", "Luguentz Dort enters the game for Kingston Flemings", "1", (4397020, 5149077),
             "8:01", home=4),
        play(41, "Shot Clock Turnover", "shot clock turnover", "1", (), "7:40", home=4),
        play(42, "Full Timeout", "Lakers Full timeout", "13", (), "7:40", home=4),
        play(43, "Technical Foul", "Luka Doncic technical foul", "13", (3945274,), "7:40", home=4),
        play(50, "Heave Jump Shot", "Luka Doncic misses heave jump shot", "13", (3945274,), "0.4", home=4,
             shooting=True, tried=3),
        play(51, "End Period", "End of the 1st Quarter", None, (), "0.0", home=4),
    ],
}


def _ids(tmp_path, monkeypatch):
    monkeypatch.setattr(raw, "RAW", tmp_path / "raw")
    return espn.Ids(INDEX)


def test_play_by_play_follows_the_stats_nba_conventions(tmp_path, monkeypatch):
    ids = _ids(tmp_path, monkeypatch)
    box, who = espn.to_box(SUMMARY, GAME, ids)
    acts = {a["actionId"]: a for a in espn.to_pbp(SUMMARY, GAME, who, ids)["game"]["actions"]}   # ESPN's numbers
    shot = acts[9]
    assert (shot["actionType"], shot["isFieldGoal"], shot["shotResult"], shot["shotValue"], shot["personId"],
            shot["teamId"], shot["location"], shot["clock"]) == ("Made Shot", 1, "Made", 3, 1630168, ATL, "h",
                                                                 "PT11M30.00S")
    assert shot["shotDistance"] == 24.0
    assert acts[4]["actionType"] == "Jump Ball" and acts[4]["teamId"] == ATL      # the jumper's team, not the tip's
    assert (acts[32]["actionType"], acts[32]["subType"], acts[32]["description"]) == (
        "Free Throw", "Free Throw 1 of 2", "MISS Okongwu Free Throw 1 of 2")
    assert acts[34]["description"] == "Okongwu Free Throw 2 of 2"
    assert (acts[33]["actionType"], acts[33]["teamId"], acts[33]["personId"]) == ("Rebound", 0, ATL)
    assert (acts[40]["actionType"], acts[40]["personId"], acts[40]["teamId"], acts[40]["description"]) == (
        "Substitution", 1643412, ATL, "SUB: Luguentz Dort FOR Kingston Flemings")
    assert (acts[41]["actionType"], acts[41]["teamId"], acts[41]["personId"]) == ("Turnover", 0, ATL)
    assert (acts[42]["actionType"], acts[42]["teamId"], acts[42]["personId"]) == ("Timeout", 0, LAL)
    assert (acts[43]["actionType"], acts[43]["subType"]) == ("Foul", "Technical")
    assert (acts[50]["actionType"], acts[50]["isFieldGoal"], acts[50]["teamId"]) == ("Heave", 0, 0)
    assert acts[50]["clock"] == "PT00M00.40S" and acts[51]["actionType"] == "period"
    rows = load.pbp_rows(espn.to_pbp(SUMMARY, GAME, who, ids))
    made = {r["action_id"]: stints.act((r["game_id"], r["action_number"], r["period"], r["clock"], r["team_id"],
                                        r["person_id"], r["action_type"], r["sub_type"], r["description"],
                                        r["is_fg"], r["shot_result"], r["score_home"], r["score_away"])).made
            for r in rows}
    assert made[9] and not made[32] and made[34]


def test_plays_go_in_clock_order_and_the_score_comes_from_the_scoring_plays(tmp_path, monkeypatch):
    """ESPN lists a late-entered play where it was entered, and its running score can be off (130-105 in a
    game that ended 127-105); its scoring plays add up to the final."""
    ids = _ids(tmp_path, monkeypatch)
    summary = {**SUMMARY, "plays": [
        play(9, "Running Jump Shot", "Onyeka Okongwu makes 24-foot running jump shot", "1", (4431680,), "11:30",
             home=3, scoring=True, shooting=True, tried=3),
        play(12, "Driving Layup Shot", "Luka Doncic makes driving layup", "13", (3945274,), "10:02", home=6,
             away=99, scoring=True, shooting=True, tried=2),                        # a junk running score
        play(11, "Personal Foul", "Kingston Flemings personal foul", "1", (5149077,), "10:40", home=3),  # late entry
    ]}
    _, who = espn.to_box(summary, GAME, ids)
    acts = espn.to_pbp(summary, GAME, who, ids)["game"]["actions"]
    assert [a["actionId"] for a in acts] == [9, 11, 12] and [a["actionNumber"] for a in acts] == [1, 2, 3]
    assert [(a["scoreHome"], a["scoreAway"]) for a in acts] == [(3, 0), (3, 0), (3, 2)]


def test_box_score_minutes_starters_and_names_come_from_the_nba_side(tmp_path, monkeypatch):
    ids = _ids(tmp_path, monkeypatch)
    box, _ = espn.to_box(SUMMARY, GAME, ids)
    rows = {r["player_id"]: r for r in load.box_rows(box)}
    luka = rows[1629029]
    assert (luka["name"], luka["team_id"], luka["seconds"], luka["starter"], luka["pts"], luka["fg3a"],
            luka["plus_minus"]) == ("Luka Dončić", LAL, 39 * 60, True, 31, 11, 10)
    assert rows[1629652]["starter"] is False and rows[1629652]["seconds"] == 18 * 60
    assert rows[1629638]["dnp"] and rows[1629638]["seconds"] == 0       # did not play: listed, no minutes


def test_names_resolve_through_nicknames_suffixes_and_teams(tmp_path, monkeypatch):
    monkeypatch.setattr(raw, "RAW", tmp_path / "raw")
    index = INDEX + [
        dict(PERSON_ID=1629651, PLAYER_FIRST_NAME="Nic", PLAYER_LAST_NAME="Claxton", TEAM_ID=1610612751,
             ROSTER_STATUS=1),
        dict(PERSON_ID=202710, PLAYER_FIRST_NAME="Jimmy", PLAYER_LAST_NAME="Butler III", TEAM_ID=1610612744,
             ROSTER_STATUS=1),
        dict(PERSON_ID=1, PLAYER_FIRST_NAME="Marcus", PLAYER_LAST_NAME="Williams", TEAM_ID=None, ROSTER_STATUS=None),
        dict(PERSON_ID=2, PLAYER_FIRST_NAME="Marcus", PLAYER_LAST_NAME="Williams", TEAM_ID=ATL, ROSTER_STATUS=1),
    ]
    ids = espn.Ids(index)
    assert ids.by_name("Nicolas Claxton", 1610612751) == 1629651
    assert ids.by_name("Jimmy Butler", 1610612744) == 202710
    assert ids.by_name("Marcus Williams", ATL) == 2                  # two players ever: the one on this team
    assert ids.resolve(77, "Nobody Known", ATL) == espn.ESPN_ID_BASE + 77
    assert 77 not in ids.map                                          # a stand-in id is not remembered
    assert ids.resolve(78, "Luka Doncic", LAL) == 1629029 and ids.map[78] == 1629029
    ids.save()
    assert espn.Ids(index).map == {78: 1629029}


def _event(eid, when, home, away, status, hs="0", as_="0"):
    return {"id": eid, "date": when, "shortName": f"{away} @ {home}", "competitions": [{
        "status": {"type": {"name": status, "shortDetail": status}},
        "competitors": [{"homeAway": "home", "team": {"abbreviation": home}, "score": hs},
                        {"homeAway": "away", "team": {"abbreviation": away}, "score": as_}]}]}


def _nba_game(gid, day, home, away, utc):
    side = lambda code, tid: {"teamId": tid, "teamTricode": code, "teamName": code, "score": 0}   # noqa: E731
    return {"gameId": gid, "gameDateEst": f"{day}T00:00:00Z", "gameDateTimeUTC": utc, "gameStatus": 1,
            "postponedStatus": "N", "homeTeam": side(*home) if home else {"teamId": 0, "teamTricode": ""},
            "awayTeam": side(*away) if away else {"teamId": 0, "teamTricode": ""}}


def test_the_schedule_takes_status_score_and_tip_from_espn(monkeypatch):
    base = {"leagueSchedule": {"gameDates": [{"games": [
        _nba_game("0022600230", "2026-11-15", ("GSW", 1610612744), ("NYK", 1610612752), "2026-11-16T00:30:00Z"),
        _nba_game("0022600231", "2026-11-16", ("SAS", 1610612759), ("UTA", 1610612762), "2026-11-17T01:00:00Z"),
        _nba_game("0022601201", "2026-12-04", None, None, "2026-12-05T00:00:00Z")]}]}}
    boards = {
        date(2026, 11, 15): [_event("1", "2026-11-16T00:30Z", "GS", "NY", "STATUS_FINAL", "112", "108")],
        date(2026, 11, 16): [_event("2", "2026-11-17T01:30Z", "SA", "UTAH", "STATUS_SCHEDULED")],
        date(2026, 12, 4): [_event("3", "2026-12-05T00:00Z", "SA", "GS", "STATUS_SCHEDULED")],
    }
    monkeypatch.setattr(espn, "scoreboard", lambda d: {"events": boards.get(d, [])})
    out = espn.schedule(base, date(2026, 11, 16), date(2026, 12, 4))
    g = {x["gameId"]: x for x in out["leagueSchedule"]["gameDates"][0]["games"]}
    assert (g["0022600230"]["gameStatus"], g["0022600230"]["homeTeam"]["score"], g["0022600230"]["awayTeam"]["score"],
            g["0022600230"]["espnId"]) == (3, 112, 108, "1")
    assert g["0022600231"]["gameDateTimeUTC"] == "2026-11-17T01:30:00Z" and g["0022600231"]["gameStatus"] == 1
    cup = g["0022601201"]
    assert (cup["homeTeam"]["teamTricode"], cup["homeTeam"]["teamId"], cup["awayTeam"]["teamTricode"]) == (
        "SAS", 1610612759, "GSW")
    assert out["source"] == "espn" and base["leagueSchedule"]["gameDates"][0]["games"][2]["homeTeam"]["teamId"] == 0
    rows = {r["game_id"]: r for r in load.schedule_rows(out, "2026-27")}
    assert rows["0022600230"]["status"] == 3 and rows["0022600230"]["home_score"] == 112


def test_rosters_move_traded_players_drop_released_ones_and_add_newcomers(tmp_path, monkeypatch):
    monkeypatch.setattr(raw, "RAW", tmp_path / "raw")
    headers = ["PERSON_ID", "PLAYER_LAST_NAME", "PLAYER_FIRST_NAME", "TEAM_ID", "TEAM_ABBREVIATION", "POSITION",
               "HEIGHT", "ROSTER_STATUS"]
    raw.save({"resultSets": [{"name": "PlayerIndex", "headers": headers, "rowSet": [
        [1630168, "Okongwu", "Onyeka", ATL, "ATL", "C", "6-8", 1],
        [1629029, "Dončić", "Luka", LAL, "LAL", "G", "6-6", 1],             # traded to ATL since
        [1629652, "Dort", "Luguentz", ATL, "ATL", "G", "6-4", 1],          # released since
    ]}]}, "players", "2026-27", "2026-11-10")
    pages = {
        "teams": {"sports": [{"leagues": [{"teams": [{"team": {"id": "1", "abbreviation": "ATL"}},
                                                     {"team": {"id": "13", "abbreviation": "LAL"}}]}]}]},
        "teams/1/roster": {"athletes": [
            {"id": "4431680", "displayName": "Onyeka Okongwu"}, {"id": "3945274", "displayName": "Luka Doncic"},
            {"id": "4684443", "displayName": "Rafael Castro", "displayHeight": "6' 10\"",
             "position": {"abbreviation": "C"}}]},
        "teams/13/roster": {"athletes": []},
    }
    monkeypatch.setattr(espn, "get", lambda path, **params: pages[path])
    ids = espn.Ids(espn.player_index())
    out = espn.rosters(ids, {"ATL": ATL, "LAL": LAL})
    rs = out["resultSets"][0]
    rows = {r["PERSON_ID"]: r for r in (dict(zip(rs["headers"], row)) for row in rs["rowSet"])}
    assert (rows[1629029]["TEAM_ID"], rows[1629029]["ROSTER_STATUS"]) == (ATL, 1)
    assert rows[1629652]["ROSTER_STATUS"] == 0
    new = rows[espn.ESPN_ID_BASE + 4684443]
    assert (new["PLAYER_FIRST_NAME"], new["PLAYER_LAST_NAME"], new["HEIGHT"], new["TEAM_ID"], new["ROSTER_STATUS"]) == (
        "Rafael", "Castro", "6-10", ATL, 1)
    on = {r["player_id"] for r in load.player_rows(out) if r["on_roster"]}
    assert on == {1630168, 1629029, espn.ESPN_ID_BASE + 4684443}


def test_learning_pairs_by_name_then_by_stat_line(tmp_path, monkeypatch):
    monkeypatch.setattr(raw, "RAW", tmp_path / "raw")
    ids = espn.Ids([])
    nba_box = {"boxScoreTraditional": {"gameId": "0022600203", "homeTeam": {"teamTricode": "ATL", "players": [
        {"personId": 1630168, "firstName": "Onyeka", "familyName": "Okongwu",
         "statistics": {"minutes": "PT29M57.00S", "points": 16, "fieldGoalsAttempted": 9}},
        {"personId": 1629652, "firstName": "Lu", "familyName": "Dort",          # a name the two sides spell apart
         "statistics": {"minutes": "PT18M03.00S", "points": 4, "fieldGoalsAttempted": 3}}]},
        "awayTeam": {"teamTricode": "LAL", "players": [
            {"personId": 1629029, "firstName": "Luka", "familyName": "Dončić",
             "statistics": {"minutes": "PT39M23.00S", "points": 31, "fieldGoalsAttempted": 24}}]}}}
    assert ids.learn(nba_box, SUMMARY) == 3
    assert ids.map == {4431680: 1630168, 4397020: 1629652, 3945274: 1629029}

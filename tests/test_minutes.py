from fof.model import minutes
from fof.store import load

T = 1


def _games():
    """Team 1's last games: 1-5 start every night; 6 plays 20 off the bench; 7 plays once and then sits."""
    out = []
    for g in range(6):
        box = [(p, 34 * 60, True) for p in range(1, 6)] + [(6, 20 * 60, False), (7, 600 if g == 0 else 0, False)]
        out.append((f"g{g}", "2024-25", T, box))
    return out


def test_every_mode_fills_240_minutes_and_knows_only_the_past():
    exp = minutes.expected(_games(), rates={0: 0.95, 1: 0.5, 2: 0.4, 3: 0.3, 4: 0.3, 5: 0.3})
    for mode in ("morning", "active", "lineup", "oracle"):
        assert abs(sum(exp[mode][("g5", T)].values()) - 240) < 1e-6
    assert ("g0", T) not in exp["morning"] or not exp["morning"][("g0", T)]     # no past yet
    m = exp["morning"][("g5", T)]
    assert m[7] < m[6] < m[1]                                  # sat out four straight games: rarely plays


def test_an_out_player_gets_no_minutes_from_the_report():
    rates = {0: 0.95, 1: 0.5}
    status = {("g5", T): {1: "Out"}}
    report_rates = {"status": {"Out": 0.0, "Questionable": 0.6}, "unlisted": {0: 0.97}}
    exp = minutes.expected(_games(), rates, status, report_rates)
    assert exp["report"][("g5", T)][1] == 0 and exp["morning"][("g5", T)][1] > 0
    assert exp["report"][("g4", T)] == exp["morning"][("g4", T)]      # no report that day: the morning numbers


def test_injury_report_stamps_in_both_formats_become_utc():
    hourly = load.injury_rows([{"player": "x"}], "2022-01-15_06PM")[0]["report_at"]
    quarter = load.injury_rows([{"player": "x"}], "2026-11-01_08_30AM")[0]["report_at"]
    assert (hourly.hour, hourly.minute) == (23, 0) and (quarter.hour, quarter.minute) == (13, 30)


def _tracker():
    """Team 1's six games as above; player 8 played team 2's last game, then joined team 1."""
    t = minutes.Tracker()
    for _, _, tid, box in _games():
        t.add(tid, box)
    t.add(2, [(8, 30 * 60, True)])
    return t


def test_tonight_follows_todays_roster():
    rates = {0: 0.95, 1: 0.5}
    t = _tracker()
    old = minutes.tonight(t, T, rates, {"status": {}}, roster=None)["report"]
    assert 6 in old and 8 not in old                     # no roster: the team's recent players only
    new = minutes.tonight(t, T, rates, {"status": {}}, roster={1, 2, 3, 4, 5, 8})["report"]
    assert 6 not in new and new[8] > 0                   # 6 has left; 8 joined, fresh from his last team
    assert abs(sum(new.values()) - 240) < 1e-6


def test_full_brings_back_the_injured_but_not_a_g_league_assignment():
    rates = {0: 0.95, 1: 0.5}
    report_rates = {"status": {"Out": 0.0, "Questionable": 0.6}, "unlisted": {0: 0.9}}
    listed = {1: ("Out", "Injury/Illness - Left Ankle; Sprain"), 6: ("Out", "G League - On Assignment")}
    m = minutes.tonight(_tracker(), T, rates, report_rates, listed=listed)
    assert m["report"][1] == 0 and m["full"][1] > 30     # back to a healthy player's minutes
    assert m["report"][6] == 0 and m["full"][6] == 0
    same = minutes.tonight(_tracker(), T, rates, report_rates, listed=None)
    assert same["report"] == same["full"]                # no report yet: nothing to bring back

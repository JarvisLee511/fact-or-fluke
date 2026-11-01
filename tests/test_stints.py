from fof.store import stints

H, A = 1, 2
PLAYERS = {11: (H, True, 1440, "One", "Player One"), 12: (H, True, 120, "Twelve", "Player Twelve"),
           13: (H, True, 1440, "Three", "Player Three"), 14: (H, True, 1440, "Four", "Player Four"),
           15: (H, True, 1440, "Five", "Player Five"), 16: (H, False, 0, "Williams", "Jalen Williams"),
           17: (H, False, 1320, "Williams", "Jaylin Williams"),
           **{p: (A, True, 1440, f"A{p}", f"Away A{p}") for p in range(21, 26)}, 26: (A, False, 0, "A26", "Away A26")}


def ev(period, clock, team, person, kind, desc="", is_fg=False, result="", score=(None, None), sub_type=""):
    return stints.act(("g", 0, period, f"PT{clock}S", team, person, kind, sub_type, desc, is_fg, result, *score))


def first_game(sub_desc="SUB: Williams FOR Twelve"):
    return [
        ev(1, "12M00.00", 0, 0, "period"),
        ev(1, "11M00.00", H, 11, "Made Shot", is_fg=True, result="Made", score=(2, 0)),
        ev(1, "10M00.00", H, 12, "Substitution", sub_desc),
        ev(1, "09M00.00", H, 17, "Missed Shot", is_fg=True, result="Missed"),     # the Williams who came in
        ev(1, "08M59.00", A, 21, "Rebound"),
        ev(1, "08M00.00", A, 22, "Made Shot", is_fg=True, result="Made", score=(2, 3)),
        ev(1, "00M00.00", 0, 0, "period"),
        ev(2, "12M00.00", 0, 0, "period"),                       # 13, 14, 15 and four of A do nothing in the 2nd
        ev(2, "06M00.00", A, 21, "Foul", sub_type="Personal"),
        ev(2, "05M00.00", H, 17, "Made Shot", is_fg=True, result="Made", score=(4, 3)),
        ev(2, "04M00.00", H, 11, "Turnover"),
        ev(2, "00M00.00", 0, 0, "period"),
    ]


def test_a_shared_family_name_goes_to_whoever_shows_up_and_quiet_starters_carry_over():
    out, check = stints.game(H, A, first_game(), PLAYERS, (4, 3))
    assert [(s["start_s"], s["end_s"]) for s in out] == [(0, 120), (120, 720), (720, 1440)]
    assert out[0]["home"] == [11, 12, 13, 14, 15]
    assert out[1]["home"] == out[2]["home"] == [11, 13, 14, 15, 17]
    assert out[2]["away"] == [21, 22, 23, 24, 25]
    assert [(s["home_pts"], s["away_pts"]) for s in out] == [(2, 0), (0, 3), (2, 0)]
    assert [(s["home_poss"], s["away_poss"]) for s in out] == [(1, 0), (1, 1), (2, 0)]
    assert check == dict(stints=3, bad_lineups=0, unknown_subs=0, max_minutes_error_s=0.0, score_ok=True, ok=True)


def test_teammates_sharing_a_family_name_are_told_apart_by_the_first_name_prefix():
    out, check = stints.game(H, A, first_game("SUB: Jay. Williams FOR Twelve"), PLAYERS, (4, 3))
    assert out[1]["home"] == [11, 13, 14, 15, 17] and check["ok"]


def test_an_unknown_incoming_name_flags_the_game():
    _, check = stints.game(H, A, first_game("SUB: Nobody FOR Twelve"), PLAYERS, (4, 3))
    assert check["unknown_subs"] == 1 and not check["ok"]


def test_clock_and_free_throw_trips():
    assert stints.clock_left("PT11M34.00S") == 694.0 and stints.clock_left("") is None
    assert stints.last_of_trip("Free Throw 2 of 2") and stints.last_of_trip("Free Throw Flagrant 1 of 1")
    assert not stints.last_of_trip("Free Throw 1 of 2") and not stints.last_of_trip("Free Throw Technical")
    assert stints.incoming("SUB: Smith Jr. FOR Green") == "Smith Jr."

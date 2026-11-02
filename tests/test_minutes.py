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

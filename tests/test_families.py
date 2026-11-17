from types import SimpleNamespace

import duckdb
import numpy as np

from fof.config import previous_season
from fof.facts import families, text
from fof.store import db


def test_peer_baseline_pools_the_closest_roles_and_never_the_player_himself(monkeypatch):
    monkeypatch.setattr(families, "ROLE_PEERS", 2)
    role = {1: np.array([0.0, 0.0]), 2: np.array([0.1, 0.0]), 3: np.array([0.2, 0.0]), 4: np.array([5.0, 5.0])}
    ctx = SimpleNamespace(role=role, name={1: "A", 2: "B", 3: "C", 4: "D"})
    base = families.peer_baseline(ctx, [(1, 10, 20), (2, 4, 20), (3, 6, 20), (4, 20, 20)])
    assert base[1] == (0.25, ["B", "C"])            # B and C: (4 + 6) / 40, never A's own 10/20
    assert base[4] == (0.25, ["C", "B"])


def test_catch_and_shoot_share_counts_threes_only_up_to_the_tracking_snapshot(monkeypatch):
    """11/17 dry run: tracking stuck at the 11/10 snapshot while ESPN box scores ran on, so every share shrank
    and 13 'rarely catches and shoots' facts were listed overnight."""
    con = duckdb.connect(":memory:")
    con.execute(db.SCHEMA)
    con.execute("""insert into games (game_id, season, season_type, game_date, tip_utc, status) values
                   ('g1', '2026-27', 'Regular Season', '2026-11-08', '2026-11-09 00:00:00', 3),
                   ('g2', '2026-27', 'Regular Season', '2026-11-12', '2026-11-13 00:00:00', 3)""")
    con.execute("""insert into player_games (game_id, player_id, team_code, name, seconds, fg3a, fga) values
                   ('g1', 1, 'BOS', 'A', 1800, 10, 15), ('g2', 1, 'BOS', 'A', 1800, 10, 15)""")
    con.execute("""insert into dash values ('2026-27', '2026-11-10', 'CatchShoot', 1, 'BOS',
                   '{"PLAYER_ID": 1, "PLAYER_NAME": "A", "CATCH_SHOOT_FG3A": 6}')""")
    seen = []
    monkeypatch.setattr(families, "peer_baseline", lambda ctx, rows: seen.extend(rows) or {})
    families.shooting_style(families.Context(con, "2026-27"))
    assert seen == [(1, 6, 10)]                     # g2 (11/12) is after the snapshot


def test_previous_season():
    assert previous_season("2026-27") == "2025-26"
    assert previous_season("2000-01") == "1999-00"


def test_every_family_has_its_sentences_in_both_directions():
    detail = dict(passer="P", receiver="R", touch="drive", zone="rim", quarter=3, peers=["X", "Y", "Z"],
                  own=0.48, league_clutch=0.44, league_other=0.47)
    named = {"touch_shoot": "touch_shoot:drive", "touch_pass": "touch_pass:elbow", "zone_fg": "zone_fg:mid"}
    for fam in families.FAMILIES:
        for k in (30, 70):
            c = dict(family=named.get(fam, fam), subject="S", k=k, n=100, p0=0.5, detail=detail, scanned=50, luck=2.0)
            zh, en = text.sentence(c)
            assert "S" in zh and "S" in en
            assert text.basis(c, "2025-26")[0].startswith("根據 100 ")
            assert text.verdict(c, "fluke")[0].startswith("光靠運氣，每 25 ")       # 2 expected among 50
    assert {cfg["kind"] for cfg in families.FAMILIES.values()} <= set(text.KIND)

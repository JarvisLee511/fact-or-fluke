import sqlite3

from fof.store import db, history_odds

COLS = "Date text, Home text, Away text, ML_Home, ML_Away, Spread, OU"


def test_lines_go_to_the_game_on_their_date_first(tmp_path):
    lite = sqlite3.connect(tmp_path / "odds.sqlite")
    for table, lines in {
        "odds_2016-17": [("2016-17-0101", "Toronto Raptors", "Cleveland Cavaliers", -999, 999, 0, 0)],  # mangled
        "odds_2016-17_new": [
            ("2017-05-05", "Toronto Raptors", "Cleveland Cavaliers", "160", -180, 4.5, 211),    # game 3
            ("2017-05-06", "Toronto Raptors", "Cleveland Cavaliers", 150, -170, "PK", 212),     # game 4, played 05-07
            ("2017-01-02", "Charlotte Bobcats", "Boston Celtics", -120, 100, -1.5, 220),
            ("2017-01-03", "Boston Celtics", "Charlotte Hornets", "NL", "NL", None, None)],
    }.items():
        lite.execute(f'create table "{table}" ({COLS})')
        lite.executemany(f'insert into "{table}" values (?, ?, ?, ?, ?, ?, ?)', lines)
    lite.commit()
    lite.close()
    con = db.connect(tmp_path / "fof.duckdb")
    db.upsert(con, "games", [dict(game_id=g, season="2016-17", game_date=d, home_code=h, away_code=a) for g, d, h, a in (
        ("g3", "2017-05-05", "TOR", "CLE"), ("g4", "2017-05-07", "TOR", "CLE"), ("cha", "2017-01-02", "CHA", "BOS"),
        ("bos", "2017-01-03", "BOS", "CHA"))])
    got = {r["game_id"]: r for r in history_odds.rows(con, tmp_path / "odds.sqlite")}
    assert sorted(got) == ["cha", "g3", "g4"]                  # no line, no row
    assert got["g3"]["ml_home"] == 160.0 and got["g4"]["ml_home"] == 150.0
    assert got["g4"]["spread"] == 0.0 and got["cha"]["ml_home"] == -120.0

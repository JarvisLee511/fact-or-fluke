"""DuckDB schema. The database is derived: delete data/fof.duckdb and scripts/build_db.py rebuilds it
from the raw archive (except the ledgers, which are written only at prediction time)."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from ..config import DATA

DB_PATH = DATA / "fof.duckdb"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id VARCHAR PRIMARY KEY, season VARCHAR, season_type VARCHAR, game_date DATE, tip_utc TIMESTAMP,
    home_id BIGINT, away_id BIGINT, home_code VARCHAR, away_code VARCHAR, home_score INTEGER, away_score INTEGER,
    status INTEGER, arena_city VARCHAR, arena_state VARCHAR, neutral BOOLEAN, label VARCHAR, subtype VARCHAR);
CREATE TABLE IF NOT EXISTS player_games (
    game_id VARCHAR, player_id BIGINT, team_id BIGINT, team_code VARCHAR, name VARCHAR, position VARCHAR,
    starter BOOLEAN, dnp BOOLEAN, seconds INTEGER, pts INTEGER, fgm INTEGER, fga INTEGER, fg3m INTEGER,
    fg3a INTEGER, ftm INTEGER, fta INTEGER, oreb INTEGER, dreb INTEGER, reb INTEGER, ast INTEGER, stl INTEGER,
    blk INTEGER, tov INTEGER, pf INTEGER, plus_minus INTEGER, PRIMARY KEY (game_id, player_id));
CREATE TABLE IF NOT EXISTS pbp (
    game_id VARCHAR, action_number INTEGER, period INTEGER, clock VARCHAR, team_id BIGINT, person_id BIGINT,
    action_type VARCHAR, sub_type VARCHAR, description VARCHAR, is_fg BOOLEAN, shot_result VARCHAR,
    shot_value INTEGER, shot_distance DOUBLE, x DOUBLE, y DOUBLE, score_home INTEGER, score_away INTEGER,
    location VARCHAR, video BOOLEAN, action_id INTEGER, PRIMARY KEY (game_id, action_number));
CREATE TABLE IF NOT EXISTS shots (
    game_id VARCHAR, event_id INTEGER, player_id BIGINT, team_id BIGINT, game_date DATE, season VARCHAR,
    season_type VARCHAR, period INTEGER, action_type VARCHAR, shot_type VARCHAR, zone_basic VARCHAR,
    zone_area VARCHAR, zone_range VARCHAR, distance INTEGER, loc_x INTEGER, loc_y INTEGER, made BOOLEAN,
    PRIMARY KEY (game_id, event_id));
CREATE TABLE IF NOT EXISTS dash (
    season VARCHAR, as_of DATE, measure VARCHAR, player_id BIGINT, team_code VARCHAR, data VARCHAR,
    PRIMARY KEY (season, as_of, measure, player_id));
CREATE TABLE IF NOT EXISTS passes (
    season VARCHAR, as_of DATE, player_id BIGINT, passer_id BIGINT, passer_name VARCHAR, passes INTEGER,
    ast INTEGER, fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER,
    PRIMARY KEY (season, as_of, player_id, passer_id));
CREATE TABLE IF NOT EXISTS players (
    player_id BIGINT PRIMARY KEY, name VARCHAR, team_code VARCHAR, position VARCHAR, height VARCHAR);
CREATE TABLE IF NOT EXISTS injuries (
    stamp VARCHAR, game_date VARCHAR, game_time VARCHAR, matchup VARCHAR, team_code VARCHAR, player VARCHAR,
    player_name VARCHAR, status VARCHAR, reason VARCHAR, PRIMARY KEY (stamp, matchup, team_code, player));
CREATE TABLE IF NOT EXISTS odds (
    taken_at TIMESTAMPTZ, event_id VARCHAR, commence_utc TIMESTAMP, home VARCHAR, away VARCHAR, book VARCHAR,
    market VARCHAR, outcome VARCHAR, price DOUBLE, point DOUBLE,
    PRIMARY KEY (taken_at, event_id, book, market, outcome));
"""


def connect(path: Path = DB_PATH, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path), read_only=read_only)
    con.execute("SET TimeZone = 'UTC'")  # naive timestamps in this DB are UTC, whatever the laptop's zone
    if not read_only:
        con.execute(SCHEMA)
    return con


def upsert(con: duckdb.DuckDBPyConnection, table: str, rows: list[dict] | pd.DataFrame) -> int:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return 0
    cols = ", ".join(df.columns)
    con.register("_rows", df)
    try:
        con.execute(f"INSERT OR REPLACE INTO {table} ({cols}) SELECT {cols} FROM _rows")
    finally:
        con.unregister("_rows")
    return len(df)

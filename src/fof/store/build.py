"""Rebuild the database from the raw archive (safe any time: every load is an upsert). Only complete files
are read: the archive writes *.json.gz.tmp first and renames when done."""
from __future__ import annotations

import json

from ..config import DATA, RAW, ROOT
from . import db, load, raw


def _seasons(kind: str):
    return sorted(p.name for p in (RAW / kind).glob("*") if p.is_dir())


def build() -> dict[str, int]:
    from ..betting import odds_rows

    con = db.connect()
    counts: dict[str, int] = {}

    def add(table: str, rows: list[dict]):
        counts[table] = counts.get(table, 0) + db.upsert(con, table, rows)

    for season in _seasons("schedule"):
        fs = raw.files("schedule", season)
        if fs:
            add("games", load.schedule_rows(raw.read(fs[-1]), season))
    for kind, loader, table in (("box", load.box_rows, "player_games"), ("pbp", load.pbp_rows, "pbp")):
        for season in _seasons("games"):
            batch: list[dict] = []
            for f in raw.files("games", season, kind):
                batch += loader(raw.read(f))
                if len(batch) > 200_000:
                    add(table, batch)
                    batch = []
            add(table, batch)
    for season in _seasons("shots"):
        for f in raw.files("shots", season):
            st = "Playoffs" if f.name.startswith("Playoffs") else "Regular Season"
            add("shots", load.shot_rows(raw.read(f), season, st))
    for season in _seasons("dash"):
        for day in sorted(p.name for p in (RAW / "dash" / season).glob("*")):
            for f in raw.files("dash", season, day):
                add("dash", load.dash_rows(raw.read(f), season, day, f.name.split(".")[0]))
    for season in _seasons("passes"):
        for day in sorted(p.name for p in (RAW / "passes" / season).glob("*")):
            batch = []
            for f in raw.files("passes", season, day):
                batch += load.pass_rows(raw.read(f), season, day)
            add("passes", batch)
    latest_index = max((f for s in _seasons("players") for f in raw.files("players", s)), default=None,
                       key=lambda p: p.name)
    if latest_index:
        add("players", load.player_rows(raw.read(latest_index)))
    for day in _seasons("odds"):
        for f in raw.files("odds", day):
            add("odds", odds_rows(raw.read(f)))
    for p in sorted((DATA / "snapshots" / "odds").glob("*/*.json")) + sorted(
            (ROOT / "private" / "snapshots" / "odds").glob("*/*.json")):
        add("odds", odds_rows(json.loads(p.read_text(encoding="utf-8"))))
    con.close()
    return counts

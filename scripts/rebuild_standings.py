"""Recompute the fun fact standings from scratch after a change to how facts are found or worded.

The current season restarts at today (listed_on = today, so tomorrow's email does not call them new); the
2025-26 demo is scored once, as of the end of that season. Then site/data/standings.json is rewritten.
Run it when no daily run is in progress."""
import sys
from datetime import date

from fof import publish
from fof.config import now_et, season_of
from fof.facts import standings
from fof.store import db

DEMO = ("2025-26", date(2026, 7, 1))

today = now_et().date()
current = season_of(today)
con = db.connect()
con.execute(standings.SCHEMA)
for season, day in [(current, today)] + ([DEMO] if current != DEMO[0] else []):
    con.execute("delete from fact_history where key in (select key from facts where season = ?)", [season])
    con.execute("delete from facts where season = ?", [season])
    print(season, standings.update(con, season, day))
seasons = [(current, current)] + ([(DEMO[0], f"{DEMO[0]} demo")] if current != DEMO[0] else [])
publish._write("standings.json", publish.standings(con, seasons))
con.close()
sys.exit(0)

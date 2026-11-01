"""Download the historical odds database the backtest compares against (see fof/store/history_odds.py for
where it comes from and its limits). Goes to data/raw/odds_history/, which never leaves this laptop."""
import os
import sqlite3
import sys

from fof.ingest.http import fetch
from fof.store.history_odds import PATH, SOURCE

PATH.parent.mkdir(parents=True, exist_ok=True)
tmp = PATH.with_suffix(".tmp")
tmp.write_bytes(fetch(SOURCE, timeout=120))
lite = sqlite3.connect(f"file:{tmp.as_posix()}?mode=ro", uri=True)
tables = sorted(r[0] for r in lite.execute("select name from sqlite_master where type = 'table'"))
lite.close()
os.replace(tmp, PATH)
print(f"{PATH}: {PATH.stat().st_size:,} bytes, {len(tables)} tables")
sys.exit(0)

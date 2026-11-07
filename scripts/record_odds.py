"""Save one odds snapshot (every upcoming NBA game, Massachusetts books) as JSON under <out>/odds/<ET date>/.

Run by the private repo's scheduled workflow. Without ODDS_API_KEY it does nothing, so the
schedule can exist before the key does. When the API is down or refuses, nothing is recorded and it still
exits 0: the next scheduled run tries again, and a failed run would only mail a failure notice.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from fof.config import now_et
from fof.ingest import odds
from fof.ingest.http import FetchError


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--bookmakers", default=odds.MA_BOOKS)
    ap.add_argument("--regions", default=None, help="use whole regions instead of the named books")
    ap.add_argument("--markets", default="h2h,spreads")
    args = ap.parse_args()

    key = os.environ.get("ODDS_API_KEY")
    if not key:
        print("ODDS_API_KEY not set; nothing recorded")
        return 0
    taken = now_et()
    try:
        games, quota = odds.snapshot(key, args.bookmakers, args.markets, args.regions)
    except FetchError as e:
        print(f"odds API unavailable, nothing recorded: {e}")
        return 0
    books = sorted({b["key"] for g in games for b in g.get("bookmakers", [])})
    tag = args.regions.replace(",", "+") if args.regions else "ma"
    path = args.out / "odds" / taken.date().isoformat() / f"{taken:%H%M%S}_{tag}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"taken_at": taken.isoformat(), "bookmakers": args.bookmakers, "regions": args.regions,
                               "markets": args.markets, "quota": quota, "games": games}, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(path)
    print(f"{len(games)} games, books {books}, credits remaining {quota.get('remaining')} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

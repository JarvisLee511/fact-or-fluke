"""One-time fetch of past official injury reports, for the backtest (network only).

The league still hosts its reports back to early 2019; a missing one answers 403. For every past game day
this keeps the report a morning prediction could have read (08:00 ET), every season first, then for every
tip-off time that day the last one 30 minutes before tip: hourly reports until 2025-12-21, every 15 minutes
since, and when the exact one is missing the closest earlier one. Each PDF is archived as it came (raw/injury_hist/<season>/<stamp>.pdf)
and, when the parser reads its layout (from early 2020; the older one needs its own parser), as rows
(<stamp>.json.gz). Resumable, keeps the laptop awake, steps aside for the morning run, and stops if a report
it fetched before is refused too (the host would be refusing us, not missing files).
Log: data/logs/backfill_injury.log
"""
from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from backfill import keep_awake, step_aside
from fof.config import DATA, ET, RAW
from fof.ingest import injury
from fof.ingest.http import FetchError
from fof.store import db, raw

SEASONS = [f"{y}-{str(y + 1)[2:]}" for y in range(2025, 2018, -1)]  # 2025-26 back to 2019-20: newest first,
                                                                     # the old sparse schedule last
QUARTER_HOURLY = date(2025, 12, 22)      # reports every 15 minutes, stamped 05_15PM, from this day on
MORNING = (8, 0)                         # what the morning run reads
BEFORE_TIP = timedelta(minutes=30)
MAX_PROBES = 16                          # earlier stamps tried per wanted time
STATUSES = {"Out", "Doubtful", "Questionable", "Probable", "Available", "Not Yet Submitted"}

log = logging.getLogger("backfill_injury")


def stamp(t: datetime) -> str:
    return t.strftime("%Y-%m-%d_%I_%M%p" if t.date() >= QUARTER_HOURLY else "%Y-%m-%d_%I%p")


def candidates(t: datetime) -> list[str]:
    """Stamps for the last report at or before t, closest first."""
    step = timedelta(minutes=15 if t.date() >= QUARTER_HOURLY else 60)
    t = t.replace(minute=t.minute - t.minute % (step.seconds // 60), second=0, microsecond=0)
    return [stamp(t - k * step) for k in range(MAX_PROBES)]


def pdf_path(season: str, s: str):
    return RAW / "injury_hist" / season / f"{s}.pdf"


def game_days() -> dict[str, dict[date, set[datetime]]]:
    """{season: {game day: tip-off times (ET)}}, read once: the morning run needs the database to itself."""
    con = db.connect(read_only=True)
    rows = con.execute("""select season, game_date, tip_utc from games where status = 3 and tip_utc is not null
                          and season_type in ('Regular Season', 'PlayIn', 'Playoffs') and season >= ?""",
                       [min(SEASONS)]).fetchall()
    con.close()
    out: dict[str, dict[date, set[datetime]]] = defaultdict(lambda: defaultdict(set))
    for season, day, tip in rows:
        if season in SEASONS:
            out[season][day].add(tip.replace(tzinfo=timezone.utc).astimezone(ET))
    return out


def main() -> int:
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=DATA / "logs" / "backfill_injury.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    keep_awake()
    missing: set[str] = set()
    known_good: tuple[str, str] | None = None
    days = game_days()
    for phase, season in [(ph, s) for ph in ("morning", "tip-off") for s in SEASONS]:
        log.info("%s reports, season %s: %d game days", phase, season, len(days[season]))
        for n, day in enumerate(sorted(days[season]), 1):
            if phase == "morning":
                wanted = {datetime(day.year, day.month, day.day, *MORNING, tzinfo=ET)}
            else:
                wanted = {tip - BEFORE_TIP for tip in days[season][day]}
            for t in sorted(wanted):
                for s in candidates(t):
                    p = pdf_path(season, s)
                    if p.exists():
                        known_good = known_good or (season, s)
                        break
                    if s in missing:
                        continue
                    step_aside()
                    try:
                        body = injury.download(s)
                    except FetchError as e:
                        if e.status not in (403, 404):
                            raise
                        missing.add(s)
                        continue
                    p.parent.mkdir(parents=True, exist_ok=True)
                    tmp = p.with_name(p.name + ".tmp")
                    tmp.write_bytes(body)
                    os.replace(tmp, p)
                    known_good = known_good or (season, s)
                    try:
                        rows = injury.parse(body)
                    except Exception:
                        rows = []
                    if rows and sum(r["status"] in STATUSES for r in rows) >= 0.8 * len(rows):
                        raw.save(rows, "injury_hist", season, s)
                    break
                else:   # nothing at or before t: missing, unless the host has started refusing us
                    if known_good:
                        try:
                            injury.download(known_good[1])
                        except FetchError as e:
                            log.error("a report fetched before is refused now (%s): stopping", e.status)
                            return 1
            if n % 25 == 0:
                got = len(list((RAW / "injury_hist" / season).glob("*.pdf")))
                log.info("  %s %s day %d/%d, %d reports", phase, season, n, len(days[season]), got)
    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

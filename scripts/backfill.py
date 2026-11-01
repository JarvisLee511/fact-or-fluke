"""One-time history fetch into the raw archive (network only; run scripts/build_db.py afterwards).

Resumable: anything already archived is skipped, so re-running after a crash, a sleep or a block
continues where it stopped. Keeps the laptop awake while it runs, and steps aside for the morning run.
Log: data/logs/backfill.log
"""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from datetime import date, timedelta
from datetime import time as clock

from fof.config import DATA, now_et, season_of, today_et
from fof.ingest import collect
from fof.ingest.http import FetchError

FULL = ["2025-26", season_of(today_et())]       # box, play-by-play, shots, dashboards, passes
HISTORY = [f"{y}-{str(y + 1)[2:]}" for y in range(2024, 2015, -1)]   # 2024-25 back to 2016-17: box, play-by-play
GAME_PREFIXES = ("002", "004", "005")           # regular season, playoffs, play-in
MORNING_RUN = (clock(5, 30), clock(13, 0))      # the daily run has stats.nba.com to itself in this window (ET)

log = logging.getLogger("backfill")


def keep_awake() -> None:
    if sys.platform == "win32":  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED: no idle sleep while this process lives
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)


def step_aside() -> None:
    """Sleep through the morning run's window, so the two never hit stats.nba.com at once."""
    now = now_et()
    if MORNING_RUN[0] <= now.time() < MORNING_RUN[1]:
        resume = now.replace(hour=MORNING_RUN[1].hour, minute=MORNING_RUN[1].minute, second=0, microsecond=0)
        log.info("pausing for the morning run until %s ET", resume.strftime("%H:%M"))
        time.sleep((resume - now).total_seconds())


def finals(payload: dict) -> list[dict]:
    games = [g for gd in payload["leagueSchedule"]["gameDates"] for g in gd["games"]
             if g["gameStatus"] == 3 and g["gameId"][:3] in GAME_PREFIXES]
    return sorted(games, key=lambda g: g["gameDateTimeUTC"])


def month_chunks(d0: date, d1: date):
    cur = d0.replace(day=1)
    while cur <= d1:
        nxt = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        yield max(cur, d0), min(nxt - timedelta(days=1), d1)
        cur = nxt


def attempt(what: str, fn):
    try:
        return fn()
    except FetchError as e:
        log.warning("skip %s: %s", what, e)
        if e.status in (401, 403):  # refused: stop instead of hammering
            raise SystemExit(f"blocked on {what}; stopping")
        return None


def main() -> int:
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=DATA / "logs" / "backfill.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if sys.stdout is not None:  # pythonw has no console
        logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    keep_awake()
    today = today_et()
    for season in FULL + HISTORY:
        step_aside()
        sched = attempt(f"schedule {season}", lambda: collect.schedule(season, today))
        if sched is None:
            continue
        games = finals(sched)
        log.info("season %s: %d final games", season, len(games))
        players: set[int] = set()
        for i, g in enumerate(games, 1):
            step_aside()
            box = attempt(f"box {g['gameId']}", lambda: collect.game("box", g["gameId"], season))
            attempt(f"pbp {g['gameId']}", lambda: collect.game("pbp", g["gameId"], season))
            if box:
                b = box["boxScoreTraditional"]
                players |= {p["personId"] for side in ("homeTeam", "awayTeam") for p in b[side]["players"]
                            if p["statistics"].get("minutes")}
            if i % 100 == 0:
                log.info("  %s games %d/%d", season, i, len(games))
        if season not in FULL:      # the model needs only box scores and play-by-play from older seasons
            continue
        days = sorted({date.fromisoformat(g["gameDateEst"][:10]) for g in games})
        current = season == FULL[-1]
        for st in (("Regular Season",) if current else ("Regular Season", "Playoffs")):
            st_days = [d for d in days if any(g["gameId"][:3] == ("002" if st == "Regular Season" else "004")
                                              and g["gameDateEst"][:10] == d.isoformat() for g in games)]
            if st_days:
                for a, b in month_chunks(st_days[0], st_days[-1]):
                    attempt(f"shots {season} {st} {a}", lambda: collect.shots(season, st, a, b))
        as_of = today if current else date(int(season[:4]) + 1, 7, 1)
        attempt(f"dashboards {season}", lambda: collect.dashboards(season, as_of))
        log.info("  %s passes for %d players", season, len(players))
        for i, pid in enumerate(sorted(players), 1):
            attempt(f"passes {season} {pid}", lambda: collect.passes(season, as_of, pid, 0))
            if i % 100 == 0:
                log.info("  %s passes %d/%d", season, i, len(players))
        attempt(f"player index {season}", lambda: collect.player_index(season, today))
    log.info("backfill done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

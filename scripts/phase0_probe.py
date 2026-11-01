"""Phase 0 feasibility probe: which data sources answer, what shape they return, and whether
last night's games are already complete. Read-only; prints a report."""
from __future__ import annotations

import io
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.stdout.reconfigure(encoding="utf-8")

from fof.config import now_et, season_of  # noqa: E402
from fof.ingest import nbastats  # noqa: E402
from fof.ingest.http import FetchError, fetch  # noqa: E402

HTML = {"Accept": "text/html,application/xhtml+xml,*/*"}


def check(name, fn):
    t0 = time.time()
    try:
        out = fn()
        print(f"[OK]   {name} ({time.time() - t0:.1f}s): {out}")
        return out
    except FetchError as e:
        print(f"[FAIL] {name} ({time.time() - t0:.1f}s): HTTP {e.status} {e.body[:160]!r}")
    except Exception as e:  # noqa: BLE001 - a probe reports every failure
        print(f"[FAIL] {name} ({time.time() - t0:.1f}s): {type(e).__name__}: {e}")
    return None


now = now_et()
today = now.date()
yday = today - timedelta(days=1)
season = season_of(today)
print(f"now (ET) {now:%Y-%m-%d %H:%M}, season {season}, checking last night = {yday}")

# 1. schedule -------------------------------------------------------------------------------
sched = {}


def schedule():
    j = nbastats.get_json("scheduleleaguev2", LeagueID="00", Season=season)
    for gd in j["leagueSchedule"]["gameDates"]:
        d = datetime.strptime(gd["gameDate"].split()[0], "%m/%d/%Y").date()
        sched[d] = gd["games"]
    n = sum(len(g) for g in sched.values())
    g0 = (sched.get(yday) or [{}])[0]
    return (f"{n} games, {len(sched)} dates; last night {len(sched.get(yday, []))} games, "
            f"today {len(sched.get(today, []))}; game keys: {sorted(g0)[:40]}")


check("stats.nba.com scheduleleaguev2", schedule)
games_y = sched.get(yday, [])
for g in games_y:
    print(f"       {g['gameId']} {g['awayTeam']['teamTricode']} @ {g['homeTeam']['teamTricode']}"
          f"  status={g.get('gameStatus')} {g.get('gameStatusText', '').strip()}  {g.get('gameDateTimeUTC')}")
for g in sched.get(today, []):
    print(f"       today {g['gameId']} {g['awayTeam']['teamTricode']} @ {g['homeTeam']['teamTricode']}"
          f"  {g.get('gameDateTimeUTC')}  label={g.get('gameLabel')!r} subtype={g.get('gameSubtype')!r}")

# 2. one of last night's games, every per-game endpoint we plan to use ------------------------
gid = games_y[0]["gameId"] if games_y else None
if gid:
    check("boxscoretraditionalv3", lambda: (lambda b: f"home players {len(b['homeTeam']['players'])}, "
          f"keys {sorted(b)[:12]}")(nbastats.get_json("boxscoretraditionalv3", GameID=gid, LeagueID="00",
          StartPeriod=0, EndPeriod=0, StartRange=0, EndRange=0, RangeType=0)["boxScoreTraditional"]))
    check("playbyplayv3", lambda: (lambda a: f"{len(a)} actions; first keys {sorted(a[0])}")(
          nbastats.get_json("playbyplayv3", GameID=gid, StartPeriod=0, EndPeriod=0)["game"]["actions"]))
    check("boxscorematchupsv3", lambda: (lambda b: f"keys {sorted(b)[:12]}; home players "
          f"{len(b['homeTeam']['players'])}")(nbastats.get_json("boxscorematchupsv3", GameID=gid,
          LeagueID="00")["boxScoreMatchups"]))
    check("boxscorehustlev2", lambda: (lambda b: f"keys {sorted(b)[:12]}")(
          nbastats.get_json("boxscorehustlev2", GameID=gid)["boxScoreHustle"]))
    check("boxscoresummaryv2 officials", lambda: [o["FIRST_NAME"] + " " + o["LAST_NAME"] for o in
          nbastats.result_sets(nbastats.get_json("boxscoresummaryv2", GameID=gid))["Officials"]])

# 3. tracking for last night only ------------------------------------------------------------
d = yday.strftime("%m/%d/%Y")
check(f"tracking Passing for {yday}", lambda: (lambda rows: f"{len(rows)} player rows, max GP "
      f"{max((r['GP'] for r in rows), default=0)}")(next(iter(nbastats.result_sets(nbastats.get_json(
      "leaguedashptstats", **{**nbastats.LEAGUE_DASH_DEFAULTS, "PtMeasureType": "Passing", "Season": season,
                              "DateFrom": d, "DateTo": d})).values()))))

# 4. scoreboard (game status for "are all of last night's games final?") ----------------------
check("scoreboardv3 today", lambda: (lambda gs: [f"{g['awayTeam']['teamTricode']}@{g['homeTeam']['teamTricode']} "
      f"{g['gameStatusText']}" for g in gs])(nbastats.get_json("scoreboardv3", GameDate=today.isoformat(),
      LeagueID="00")["scoreboard"]["games"]))

# 5. official injury report ------------------------------------------------------------------
pdf_links = []


def injury_page():
    tag = f"{season[:4]}-{int(season[:4]) + 1 - 2000:02d}"
    url = f"https://official.nba.com/nba-injury-report-{season[:4]}-{tag[-2:]}-season/"
    html = fetch(url, HTML).decode("utf-8", "replace")
    pdf_links.extend(sorted(set(re.findall(r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_[^\"'<> ]+?\.pdf", html))))
    return f"{url} -> {len(pdf_links)} PDF links; latest {pdf_links[-3:]}"


check("official.nba.com injury report page", injury_page)


def injury_pdf():
    import pdfplumber
    raw = fetch(pdf_links[-1], {"Accept": "application/pdf,*/*"})
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        text = pdf.pages[0].extract_text() or ""
        return f"{len(raw)} bytes, {len(pdf.pages)} pages; page 1 starts:\n" + "\n".join(text.splitlines()[:14])


if pdf_links:
    check("latest injury report PDF", injury_pdf)

# 6. transactions ----------------------------------------------------------------------------
def moves():
    j = json.loads(fetch("https://stats.nba.com/js/data/playermovement/NBA_Player_Movement.json",
                         nbastats.STATS_HEADERS))
    rows = j["NBA_Player_Movement"]["rows"]
    rows.sort(key=lambda r: r.get("TRANSACTION_DATE", ""))
    tail = [f"{r.get('TRANSACTION_DATE', '')[:10]} {r.get('Transaction_Type')}: {r.get('TRANSACTION_DESCRIPTION')}"
            for r in rows[-4:]]
    return f"{len(rows)} rows; keys {sorted(rows[-1])}; latest:\n       " + "\n       ".join(tail)


check("NBA player movement (transactions)", moves)

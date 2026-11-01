"""Daily pipeline (laptop). Scheduled every 30 minutes from 06:00 ET; each ET day is processed once.

collect  refresh the schedule, fetch last night's box scores and play-by-play, check whether last night's
         tracking data is out; once it is (or at the noon cutoff, D5) fetch season-to-date dashboards,
         passes, shots, the injury report and an odds snapshot
analyze  rebuild the DB, advance the fun fact standings, find last night's records, predict today's games
         (never after tip-off), append to the ledgers, email the digest, push the private repo
Progress is checkpointed in data/state/<day>.json; a lock file stops two runs overlapping.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, time, timedelta

from . import betting, digest, ledger, publish
from .config import DATA, ET, ROOT, now_et, season_of
from .facts import records, standings
from .ingest import collect, injury, odds
from .ingest import nbastats as ns
from .ingest.http import FetchError
from .model import baseline
from .notify import email
from .store import build, db, raw

MODEL = "baseline-elo-context-v1"
SITE_URL = "https://jarvislee511.github.io/fact-or-fluke/"
CUTOFF = time(12, 0)
GAME_PREFIXES = ("002", "004", "005", "006")
STATE = DATA / "state"
GIT_AUTH = ["-c", "credential.helper=",
            "-c", 'credential.helper=!f(){ echo username=x-access-token; echo "password=$(gh auth token)"; };f']

log = logging.getLogger("fof")


def _state(day: date) -> dict:
    p = STATE / f"{day}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _save_state(day: date, st: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    tmp = STATE / f"{day}.json.tmp"
    tmp.write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, STATE / f"{day}.json")


def _lock() -> bool:
    STATE.mkdir(parents=True, exist_ok=True)
    p = STATE / "run.lock"
    if p.exists():
        try:
            pid = int(p.read_text())
            os.kill(pid, 0)
            return False              # another run is alive
        except (ValueError, OSError):
            pass                      # stale lock
    p.write_text(str(os.getpid()))
    return True


def collect_day(day: date, force: bool) -> dict:
    season, yday = season_of(day), day - timedelta(days=1)
    sched = collect.schedule(season, day)
    games = [g for gd in sched["leagueSchedule"]["gameDates"] for g in gd["games"]
             if g["gameDateEst"][:10] == yday.isoformat() and g["gameId"][:3] in GAME_PREFIXES
             and g.get("postponedStatus") != "Y"]
    finals = [g for g in games if g["gameStatus"] == 3]
    played: set[int] = set()
    for g in finals:
        box = collect.game("box", g["gameId"], season)
        collect.game("pbp", g["gameId"], season)
        played |= {p["personId"] for side in ("homeTeam", "awayTeam")
                   for p in box["boxScoreTraditional"][side]["players"] if p["statistics"].get("minutes")}
    regular = [g for g in finals if g["gameId"].startswith("002")]
    tracking_ready = True
    if regular:
        d = yday.strftime("%m/%d/%Y")
        rows = next(iter(ns.result_sets(ns.get_json("leaguedashptstats", **{
            **ns.LEAGUE_DASH_DEFAULTS, "PtMeasureType": "Passing", "Season": season,
            "DateFrom": d, "DateTo": d})).values()), [])
        tracking_ready = len(rows) > 0
    complete = len(finals) == len(games) and tracking_ready
    info = {"finals": len(finals), "scheduled": len(games), "tracking_ready": tracking_ready,
            "complete": complete, "partial": not complete}
    if not complete and not force and now_et().time() < CUTOFF:
        return {**info, "go": False}
    if tracking_ready:  # otherwise these would still show yesterday's totals; keep the last good snapshot
        collect.dashboards(season, day, refresh=True)
        for pid in sorted(played):
            try:
                collect.passes(season, day, pid, 0, refresh=True)
            except FetchError as e:
                log.warning("passes %s: %s", pid, e)
    if regular:
        collect.shots(season, "Regular Season", yday, yday, refresh=True)
    try:
        stamp = injury.latest_stamps(season)[-1]
        raw.save(injury.parse(injury.download(stamp)), "injury", day.isoformat(), stamp)
    except (FetchError, IndexError) as e:
        log.warning("injury report: %s", e)
    key = os.environ.get("ODDS_API_KEY")
    if key:
        games_odds, quota = odds.snapshot(key)
        raw.save({"taken_at": now_et().isoformat(), "quota": quota, "games": games_odds},
                 "odds", day.isoformat(), now_et().strftime("%H%M%S"))
    _git(["pull", "-q", "--rebase"])
    return {**info, "go": True}


def _git(args: list[str], repo=None) -> None:
    """git in the private repo by default (ledger, snapshots), or the public one (site data)."""
    repo = repo or ROOT / "private"
    if (repo / ".git").exists():
        r = subprocess.run(["git", "-C", str(repo), *GIT_AUTH, *args], capture_output=True, text=True, timeout=120)
        if r.returncode:
            log.warning("git %s: %s", " ".join(args), (r.stderr or r.stdout).strip()[:300])


def predict(con, day: date) -> list[dict]:
    cols = ["game_id", "season", "game_date", "tip_utc", "home_id", "away_id", "home_code", "away_code",
            "home_score", "away_score", "neutral", "status"]
    games = [dict(zip(cols, r)) for r in con.execute(
        f"select {', '.join(cols)} from games where tip_utc is not null order by tip_utc").fetchall()]
    rows = baseline.feature_rows(games)
    first = min(r["season"] for r in rows)
    train = [r for r in rows if r["status"] == 3 and r["game_date"] < day
             and not (r["season"] == first and r["game_date"].month == 10)]
    import numpy as np
    w = baseline.fit(np.array([r["x"] for r in train]),
                     np.array([float(r["home_score"] > r["away_score"]) for r in train]))
    now = now_et()
    out = []
    for r in rows:
        tip = r["tip_utc"].replace(tzinfo=__import__("zoneinfo").ZoneInfo("UTC"))
        if r["game_date"] != day or r["status"] == 3 or tip <= now:
            continue
        p = float(baseline.predict(w, np.array([r["x"]]))[0])
        why = {}  # each factor's share: home win probability with it minus without it (percentage points)
        for i, name in enumerate(baseline.FEATURES):
            x0 = list(r["x"])
            x0[i] = 0.0
            why[name] = round(p - float(baseline.predict(w, np.array([x0]))[0]), 4)
        mv = betting.market_view(con, r["home_code"], r["away_code"], day, now)
        val = betting.value(p, mv, r["home_code"], r["away_code"]) if mv else {"ev": None, "pick": None,
                                                                               "suspect": None}
        out.append(dict(
            id=f"{r['game_id']}:v1", made_at=now.isoformat(), version="v1", model=MODEL, game_id=r["game_id"],
            game_date=day.isoformat(), tip_utc=tip.isoformat(), home=r["home_code"], away=r["away_code"],
            p_home=round(p, 4), features=dict(zip(baseline.FEATURES, [round(x, 3) for x in r["x"]])), why=why,
            elo=[round(r["elo_home"], 1), round(r["elo_away"], 1)],
            market_p_home=round(mv["market_p_home"], 4) if mv and mv["market_p_home"] else None,
            odds_taken_at=str(mv["taken_at"]) if mv else None, best=mv["best"] if mv else None,
            ev={k: round(v, 4) for k, v in val["ev"].items()} if val["ev"] else None, pick=val["pick"],
            suspect=val.get("suspect")))
    return out


def scorecard(con, day: date) -> dict:
    results = {gid: (h > a) for gid, h, a in con.execute(
        "select game_id, home_score, away_score from games where status = 3").fetchall()}
    preds = [p for p in ledger.read(ledger.PREDICTIONS) if p["game_id"] in results]
    yday = (day - timedelta(days=1)).isoformat()

    def summary(ps):
        if not ps:
            return {}
        mk = [p for p in ps if p.get("market_p_home") is not None]
        return {"n": len(ps), "model_correct": sum((p["p_home"] > 0.5) == results[p["game_id"]] for p in ps),
                "market_n": len(mk),
                "market_correct": sum((p["market_p_home"] > 0.5) == results[p["game_id"]] for p in mk)}
    bets = [b for b in ledger.read(ledger.BETS) if b["game_id"] in results]
    settled = [betting.settle(b["price"], results[b["game_id"]] == (b["side"] == "home")) for b in bets]
    return {"all": summary(preds), "yesterday": summary([p for p in preds if p["game_date"] == yday]),
            "bets": {"n": len(bets), "wins": sum(s[0] > 0 for s in settled),
                     "profit": sum(s[0] for s in settled), "profit_after_tax": sum(s[1] for s in settled)}}


def analyze(day: date, partial: bool, send: bool, push: bool = True) -> dict:
    counts = build.build()
    con = db.connect()
    season = season_of(day)
    changes = standings.update(con, season, day)
    recs = records.last_night(con, day - timedelta(days=1))
    made = predict(con, day)
    n_pred = ledger.append(ledger.PREDICTIONS, made)
    n_bet = ledger.append(ledger.BETS, [dict(
        id=f"{p['game_id']}:v1:bet", pred_id=p["id"], game_id=p["game_id"], game_date=p["game_date"],
        side="home" if p["pick"] == p["home"] else "away", team=p["pick"], price=p["best"][p["pick"]][0],
        book=p["best"][p["pick"]][1], stake=betting.STAKE, ev=p["ev"][p["pick"]], made_at=p["made_at"])
        for p in made if p.get("pick")])
    preds = sorted((p for p in ledger.read(ledger.PREDICTIONS) if p["game_date"] == day.isoformat()),
                   key=lambda p: p["tip_utc"])                       # the email shows what the ledger holds
    card = scorecard(con, day)
    listed_total = con.execute("select count(*) from facts where season = ? and status = 'listed'",
                               [season]).fetchone()[0]
    publish.publish(con, day, season, card, recs, partial)
    con.close()
    subject, text, html_doc = digest.compose(day, preds, card, changes, listed_total, recs, partial, SITE_URL)
    sent = email.send(subject, text, html_doc) if send else None
    if push:
        _git(["add", "ledger"])
        _git(["commit", "-q", "-m", f"ledger {day}"])
        _git(["push", "-q"])
        _git(["add", "site/data"], ROOT)
        _git(["commit", "-q", "-m", f"site data {day}"], ROOT)
        _git(["push", "-q"], ROOT)
    return {"rows": counts, "standings": changes, "records": len(recs), "predictions_new": n_pred,
            "bets_new": n_bet, "email": sent}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", type=date.fromisoformat, default=None)
    ap.add_argument("--force", action="store_true", help="skip the wait for complete data")
    ap.add_argument("--no-email", action="store_true")
    ap.add_argument("--dry", action="store_true", help="local only: no email, no git push")
    args = ap.parse_args(argv)
    if args.dry:
        args.no_email = True
    day = args.day or now_et().date()
    (DATA / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=DATA / "logs" / f"run-{day}.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if sys.stdout is not None:
        logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))
    if not _lock():
        log.info("another run is in progress")
        return 0
    try:
        st = _state(day)
        if st.get("emailed"):
            log.info("%s already done", day)
            return 0
        if not st.get("collected"):
            info = collect_day(day, args.force)
            log.info("collect: %s", info)
            if not info["go"]:
                return 0
            st.update(collected=True, partial=info["partial"])
            _save_state(day, st)
        result = analyze(day, st.get("partial", False), send=not args.no_email, push=not args.dry)
        st.update(emailed=not args.no_email, result=result, finished=now_et().isoformat())
        _save_state(day, st)
        log.info("done: %s", result)
        return 0
    finally:
        (STATE / "run.lock").unlink(missing_ok=True)

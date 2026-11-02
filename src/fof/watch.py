"""Pre-game watch (D4), run in the cloud by the private repo's workflow every 15 minutes from 16:00 ET until
the day's last tip.

The daily run leaves a table in the private repo (watch/<day>.json): for each game, every player who might
play with his minutes when he plays, run of missed games and rating, the statuses the morning used, and the
model's weights. Here the latest official injury report is read and, for each game not started yet, a team
whose statuses differ from the last ones acted on gets the morning model recomputed with the new statuses
(fof.model.minutes.project, the code the morning ran). An email goes out when the home win probability moved
5 points or more from the last number sent, or a usual starter of a followed team changed status; every
recompute is logged to ledger/pregame.jsonl (append-only, before tip). Before each tip the closing odds are
recorded (snapshots/odds/<day>/, read by the daily build), for closing line value.

Everything is read from and written to the private repo checkout; the day's state sits in
watch/<day>.state.json, so a run that dies is redone by the next one.
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

from . import betting, digest, ledger
from .config import ET, now_et, season_of
from .ingest import injury, odds
from .ingest.http import FetchError
from .model import minutes
from .notify import email

MOVE = 0.05                              # D4: this far from the last number sent
START = time(16, 0)                      # ET
CLOSE_AHEAD = timedelta(minutes=30)      # closing odds for the games tipping this soon
SHOWN = 4                                # status changes listed per game in an email
STATUS_ZH = {"Out": "缺陣", "Doubtful": "大概不打", "Questionable": "不確定", "Probable": "應該會打",
             "Available": "可以打", None: "不在傷兵名單"}
LEVEL = {None: 0, "Available": 0, "Probable": 0, "Questionable": 1, "Doubtful": 2, "Out": 2}   # plays / maybe / sits


def load_table(path: Path) -> dict:
    """watch/<day>.json, with player ids and streak lengths back to ints."""
    t = json.loads(path.read_text(encoding="utf-8"))
    for g in t["games"]:
        for team in g["teams"].values():
            team["players"] = {int(p): v for p, v in team["players"].items()}
            team["listed"] = _listed(team["listed"])
            team["names"] = {k: int(p) for k, p in team["names"].items()}
    t["rates"] = {int(k): v for k, v in t["rates"].items()}
    t["report_rates"]["unlisted"] = {int(k): v for k, v in t["report_rates"]["unlisted"].items()}
    return t


def _listed(raw: dict | None) -> dict[int, tuple[str, str]] | None:
    return None if raw is None else {int(p): tuple(v) for p, v in raw.items()}


def win_prob(table: dict, game: dict, listed: dict) -> tuple[float, float]:
    """The morning model's home win probability with these statuses ({side: {player: (status, reason)} or
    None}), and home strength minus away."""
    s = {}
    for side in ("home", "away"):
        team = game["teams"][side]
        m = minutes.project(team["players"], table["rates"], table["report_rates"], listed[side])["report"]
        s[side] = sum(v / 48.0 * team["players"][p]["rating"] for p, v in m.items())
    x = list(game["x"]) + [s["home"] - s["away"]]
    w = table["weights"]
    return 1.0 / (1.0 + math.exp(-(w[0] + sum(a * b for a, b in zip(w[1:], x))))), x[-1]


def new_state(table: dict) -> dict:
    return {"stamp": None, "games": {g["game_id"]: {
        "listed": {side: g["teams"][side]["listed"] for side in ("home", "away")},
        "p_sent": g["p_home"], "closed": False} for g in table["games"]}}


def load_state(path: Path, table: dict) -> dict:
    st = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if "games" not in st:           # first look today, or only the missing-table alert so far
        return new_state(table)
    for gs in st["games"].values():
        gs["listed"] = {side: _listed(v) for side, v in gs["listed"].items()}
    return st


def report_lines(report: list[dict], day: date, game: dict) -> list[tuple[str, str, str, str]]:
    """One game's lines on a parsed report, as (team, player name, status, reason)."""
    d, matchup = day.strftime("%m/%d/%Y"), f"{game['away']}@{game['home']}"
    return [(r.get("team_tricode") or "", r.get("player_name") or "", r.get("status") or "", r.get("reason") or "")
            for r in report if r.get("game_date") == d and r.get("matchup") == matchup]


def step(table: dict, state: dict, report: list[dict], now: datetime) -> list[dict]:
    """Read one new report: for each game not started whose statuses changed, the recomputed probability and
    whether it is worth an email. Updates the statuses in `state` (the caller saves it)."""
    day = date.fromisoformat(table["day"])
    out = []
    for g in table["games"]:
        if datetime.fromisoformat(g["tip_utc"]) <= now:
            continue
        gs = state["games"][g["game_id"]]
        lines = report_lines(report, day, g)
        new, changes = {}, []
        for side in ("home", "away"):
            team = g["teams"][side]
            last = gs["listed"][side]
            found = minutes.team_status(lines, team["code"], team["names"]) if lines else None
            cur = found if found is not None else last          # not filed on this report: keep what we had
            for pid in sorted(set(last or {}) | set(cur or {})):
                before, after = (last or {}).get(pid, (None,))[0], (cur or {}).get(pid, (None,))[0]
                if before != after:
                    who = team["players"].get(pid, {})
                    changes.append(dict(team=team["code"], player=pid, name=who.get("name", str(pid)),
                                        before=before, after=after, starter=bool(who.get("starter")),
                                        min=who.get("min", 0.0)))
            new[side] = cur
        if not changes:
            continue
        p, x = win_prob(table, g, new)
        moved = abs(p - gs["p_sent"]) >= MOVE
        starter = any(c["starter"] and c["team"] in table["followed"] and LEVEL.get(c["before"], 1) != LEVEL.get(c["after"], 1)
                      for c in changes)                  # D4: a followed team's starter now more or less likely to play
        changes.sort(key=lambda c: (-c["min"], c["name"]))   # the players who play the most first
        out.append(dict(game=g, changes=changes, p_before=gs["p_sent"], p=p, x=x, moved=moved, starter=starter,
                        push=moved or starter))
        gs["listed"] = new
    return out


def due_closing(table: dict, state: dict, now: datetime) -> list[str]:
    return [g["game_id"] for g in table["games"] if not state["games"][g["game_id"]]["closed"]
            and now < datetime.fromisoformat(g["tip_utc"]) <= now + CLOSE_AHEAD]


def priced(u: dict, snap: dict | None) -> dict:
    """The update as a prediction row: its probability against the market of the same moment."""
    g = u["game"]
    row = dict(home=g["home"], away=g["away"], p_home=u["p"], market_p_home=None, odds_taken_at=None, best=None,
               ev=None, pick=None, suspect=None)
    mv = betting.view_from_snapshot(snap["games"], g["home"], g["away"], datetime.fromisoformat(g["tip_utc"]),
                                    snap["taken_at"]) if snap else None
    if mv:
        val = betting.value(u["p"], mv, g["home"], g["away"])
        row.update(market_p_home=mv["market_p_home"], odds_taken_at=mv["taken_at"], best=mv["best"],
                   ev=val["ev"], pick=val["pick"], suspect=val["suspect"])
    return row


def message(pushes: list[tuple[dict, dict]], now: datetime) -> tuple[str, str, str]:
    """Subject, text and HTML for one run's updates ((update, priced row) pairs)."""
    title = f"【賽前更新 {now.astimezone(ET):%H:%M}】"
    out = [title]
    for u, row in pushes:
        g = u["game"]
        tip = datetime.fromisoformat(g["tip_utc"]).astimezone(ET)
        out += ["", f"{g['away']} @ {g['home']}（{tip:%H:%M} 開打）"]
        out += [f"{c['team']}：{c['name']} {STATUS_ZH.get(c['before'], c['before'])} → "
                f"{STATUS_ZH.get(c['after'], c['after'])}" for c in u["changes"][:SHOWN]]
        if len(u["changes"]) > SHOWN:
            out.append(f"另有 {len(u['changes']) - SHOWN} 人狀態變動")
        home_side = u["changes"][0]["team"] == g["home"]
        team = g["home"] if home_side else g["away"]
        before, after = (u["p_before"], u["p"]) if home_side else (1 - u["p_before"], 1 - u["p"])
        why = "" if u["moved"] else "（關注球隊的先發球員狀態改變）"
        out.append(f"{team} 勝率 {before:.0%} → {after:.0%}{why}")
        mk = row.get("market_p_home")
        if mk is not None:
            out.append(f"賭盤：{g['home'] if mk >= 0.5 else g['away']} {max(mk, 1 - mk):.0%}")
        out.append(digest.value_line(row))
    out += ["", "這是分析和娛樂，不是投資建議。"]
    text = "\n".join(out)
    body = "".join(f"<div>{line or '&nbsp;'}</div>" for line in map(_escape, out))
    html_doc = ('<div style="font-family:\'Microsoft JhengHei\',\'PingFang TC\',sans-serif;font-size:15px;'
                f'line-height:1.6;color:#1f2328">{body}</div>')
    games = "、".join(f"{u['game']['away']}@{u['game']['home']}" for u, _ in pushes)
    return f"Fact or Fluke｜賽前更新 {now.astimezone(ET):%H:%M}｜{games}", text, html_doc


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _snapshot(key: str, repo: Path, tag: str) -> dict | None:
    """One h2h odds snapshot (1 credit), kept like record_odds.py keeps its own; None if the API refused (the
    numbers still go out, without prices)."""
    try:
        games, quota = odds.snapshot(key, markets="h2h")
    except FetchError:
        return None
    taken = now_et()
    snap = {"taken_at": taken.isoformat(), "bookmakers": odds.MA_BOOKS, "regions": None, "markets": "h2h",
            "quota": quota, "games": games}
    _write(repo / "snapshots" / "odds" / taken.date().isoformat() / f"{taken:%H%M%S}_{tag}.json", snap)
    return snap


def _report(day: date) -> tuple[list[dict], str]:
    """The latest official report, parsed. Raises FetchError when it cannot be had or read this time."""
    stamp = injury.latest_stamps(season_of(day))[-1]
    body = injury.download(stamp)
    try:
        return injury.parse(body), stamp
    except Exception as e:                       # a PDF the parser cannot read: wait for the next one
        raise FetchError(f"report {stamp} (unreadable: {e})", None) from e


def run(repo: Path, now: datetime | None = None, dry: bool = False) -> dict:
    """One look. `dry`: no odds calls, email or writes, just what would happen."""
    now = (now or now_et()).astimezone(ET)
    day = now.date()
    if now.time() < START:
        return {"skip": "before 16:00 ET"}
    tpath, spath = repo / "watch" / f"{day}.json", repo / "watch" / f"{day}.state.json"
    if not tpath.exists():
        return _no_table(day, spath, dry)
    table = load_table(tpath)
    if all(datetime.fromisoformat(g["tip_utc"]) <= now for g in table["games"]):
        return {"skip": "every game has started"}
    state = load_state(spath, table)
    key = None if dry else os.environ.get("ODDS_API_KEY")
    snap, closing = None, due_closing(table, state, now)
    if closing and key:
        snap = _snapshot(key, repo, "close")
        for gid in closing if snap else ():
            state["games"][gid]["closed"] = True
    try:
        report, stamp = _report(day)
    except (FetchError, IndexError) as e:      # the report page is down: try again next time
        if not dry:
            _write(spath, state)
        return {"closing": closing, "report": f"unavailable ({e})"}
    updates = step(table, state, report, now) if stamp != state["stamp"] else []
    state["stamp"] = stamp
    pushes = [u for u in updates if u["push"]]
    if pushes and snap is None and key:
        snap = _snapshot(key, repo, "pre")
    rows = [(u, priced(u, snap)) for u in updates]
    sent = None
    if pushes and not dry:
        sent = email.send(*message([(u, r) for u, r in rows if u["push"]], now))
    for u, _ in rows:
        if u["push"] and not dry:
            state["games"][u["game"]["game_id"]]["p_sent"] = u["p"]
    if not dry:
        ledger.append(repo / "ledger" / "pregame.jsonl", [_ledger_row(table, u, r, stamp, now) for u, r in rows])
        _write(spath, state)
    return {"report": stamp, "closing": closing, "updates": len(updates), "pushes": len(pushes), "email": sent,
            "games": [f"{u['game']['away']}@{u['game']['home']} {u['p_before']:.3f}->{u['p']:.3f}"
                      f"{' push' if u['push'] else ''}" for u in updates]}


def _ledger_row(table: dict, u: dict, row: dict, stamp: str, now: datetime) -> dict:
    g = u["game"]
    return dict(id=f"{g['game_id']}:{table['version']}:pre:{now.astimezone(ET):%H%M}", made_at=now.isoformat(),
                kind="pregame", model=table["model"], version=table["version"], game_id=g["game_id"],
                game_date=table["day"], tip_utc=g["tip_utc"], home=g["home"], away=g["away"],
                p_home=round(u["p"], 4), p_morning=g["p_home"], p_before=round(u["p_before"], 4),
                report=round(u["x"], 3), report_stamp=stamp,
                changes=[{k: c[k] for k in ("team", "player", "name", "before", "after")} for c in u["changes"]],
                pushed=u["push"], trigger="move" if u["moved"] else "starter" if u["starter"] else None,
                market_p_home=round(row["market_p_home"], 4) if row["market_p_home"] is not None else None,
                odds_taken_at=row["odds_taken_at"], best=row["best"],
                ev={k: round(v, 4) for k, v in row["ev"].items() if v is not None} if row["ev"] else None,
                pick=row["pick"], suspect=row["suspect"])


def _no_table(day: date, spath: Path, dry: bool) -> dict:
    """No table from this morning: say so once, if there are games today."""
    st = json.loads(spath.read_text(encoding="utf-8")) if spath.exists() else {}
    if st.get("alerted"):
        return {"skip": "no table (already said so)"}
    try:
        report, _ = _report(day)
    except (FetchError, IndexError) as e:
        return {"skip": f"no table, report unavailable ({e})"}
    if not any(r.get("game_date") == day.strftime("%m/%d/%Y") for r in report):
        return {"skip": "no games today"}
    if dry:
        return {"skip": "no table; would alert"}
    sent = email.send(f"Fact or Fluke｜{day.month}/{day.day} 賽前監看停用",
                      f"今天早上的對照表（watch/{day}.json）沒有上傳，今晚不會有賽前補推。\n"
                      f"多半是筆電早上的排程沒跑完，可以看 data/logs/run-{day}.log。",
                      f"<div>今天早上的對照表（watch/{day}.json）沒有上傳，今晚不會有賽前補推。</div>"
                      f"<div>多半是筆電早上的排程沒跑完，可以看 data/logs/run-{day}.log。</div>")
    _write(spath, {"alerted": True})
    return {"alert": sent}

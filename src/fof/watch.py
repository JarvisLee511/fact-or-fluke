"""Pre-game watch (D4, as revised 2026-11-02: an email only when the advice changes), run in the cloud by the
private repo's workflow every 15 minutes from 16:00 ET until the day's last tip.

The daily run leaves a table in the private repo (watch/<day>.json): for each game, every player who might
play with his minutes when he plays, run of missed games and rating, the statuses the morning used, and the
model's weights; the morning's advice is in the ledger it wrote (ledger/predictions.jsonl). Here the latest
official injury report is read and, for each game not started yet, a team whose statuses differ from the last
ones acted on gets the morning model recomputed with the new statuses (fof.model.minutes.project, the code the
morning ran). When the new number, at the last prices seen, would change which side is worth a paper bet (D3),
the odds are fetched (1 credit) and the game judged again at the prices of the moment. An email goes out only
when the advice changed: a bet newly worth it (kept in a paper book of its own, ledger/bets_pregame.jsonl) or
one no longer worth it. Every recompute is logged to ledger/pregame.jsonl (append-only, before tip). Before
each tip the closing odds are recorded (snapshots/odds/<day>/, read by the daily build), for closing line value.

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

START = time(16, 0)                      # ET
CLOSE_AHEAD = timedelta(minutes=30)      # closing odds for the games tipping this soon
NEWS_SHOWN = 2                           # status changes named per game in an email
STATUS_ZH = {"Out": "缺陣", "Doubtful": "大概不打", "Questionable": "不確定", "Probable": "應該會打",
             "Available": "可以打", None: "不在傷兵名單"}


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


def morning_rows(repo: Path, table: dict) -> dict[str, dict]:
    """The morning's prediction per game, as the email read it (ledger.for_day): its pick, prices and market."""
    rows: dict[str, dict] = {}
    for p in ledger.read(repo / "ledger" / "predictions.jsonl"):
        if p["game_date"] == table["day"] and (p["game_id"] not in rows or p.get("model") == table["model"]):
            rows[p["game_id"]] = p
    return rows


def new_state(table: dict, morning: dict[str, dict] | None = None) -> dict:
    """Each game's statuses and probability as the morning left them, the side advised (the morning's pick) and
    the prices that advice was judged at."""
    games = {}
    for g in table["games"]:
        m = (morning or {}).get(g["game_id"], {})
        view = ({"taken_at": m.get("odds_taken_at"), "market_p_home": m.get("market_p_home"), "best": m["best"]}
                if m.get("best") else None)
        games[g["game_id"]] = {"listed": {side: g["teams"][side]["listed"] for side in ("home", "away")},
                               "p": g["p_home"], "closed": False, "morning": m.get("pick"), "pick": m.get("pick"),
                               "view": view}
    return {"stamp": None, "games": games}


def load_state(path: Path, table: dict, morning: dict[str, dict] | None = None) -> dict:
    st = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if "games" not in st:           # first look today, or only the missing-table alert so far
        return new_state(table, morning)
    fresh = new_state(table, morning)["games"]
    for gid, gs in st["games"].items():
        gs["listed"] = {side: _listed(v) for side, v in gs["listed"].items()}
        if "p_sent" in gs:          # a state saved before the advice-only email: fill in what it lacks
            gs["p"] = gs.pop("p_sent")
        for k, v in fresh.get(gid, {}).items():
            gs.setdefault(k, v)
    return st


def report_lines(report: list[dict], day: date, game: dict) -> list[tuple[str, str, str, str]]:
    """One game's lines on a parsed report, as (team, player name, status, reason)."""
    d, matchup = day.strftime("%m/%d/%Y"), f"{game['away']}@{game['home']}"
    return [(r.get("team_tricode") or "", r.get("player_name") or "", r.get("status") or "", r.get("reason") or "")
            for r in report if r.get("game_date") == d and r.get("matchup") == matchup]


def step(table: dict, state: dict, report: list[dict], now: datetime) -> list[dict]:
    """Read one report: for each game not started whose statuses differ from the last ones acted on, the
    changes and the probability recomputed with the new statuses. The caller acts on them and keeps the
    statuses it acted on (state is not touched here)."""
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
                                        before=before, after=after, min=who.get("min", 0.0)))
            new[side] = cur
        if not changes:
            continue
        p, x = win_prob(table, g, new)
        changes.sort(key=lambda c: (-c["min"], c["name"]))   # the players who play the most first
        out.append(dict(game=g, changes=changes, listed=new, p_before=gs["p"], p=p, x=x))
    return out


def due_closing(table: dict, state: dict, now: datetime) -> list[str]:
    return [g["game_id"] for g in table["games"] if not state["games"][g["game_id"]]["closed"]
            and now < datetime.fromisoformat(g["tip_utc"]) <= now + CLOSE_AHEAD]


def priced(game: dict, p: float, view: dict | None) -> dict:
    """A probability as a prediction row, against the prices of `view` (one moment's market) when there is one."""
    row = dict(home=game["home"], away=game["away"], p_home=p, market_p_home=None, odds_taken_at=None, best=None,
               ev=None, pick=None, suspect=None)
    if view:
        row.update(market_p_home=view["market_p_home"], odds_taken_at=view["taken_at"], best=view["best"],
                   **betting.value(p, view, game["home"], game["away"]))
    return row


def may_change(u: dict, gs: dict) -> bool:
    """Whether a recompute could change the advice: at the last prices seen, the verdict (the side worth a bet,
    and the side the sanity check holds back) is not the one the last number got. With no prices yet, only
    fresh ones can tell."""
    if gs["view"] is None:
        return True
    verdict = [(r["pick"], r["suspect"]) for r in (priced(u["game"], p, gs["view"]) for p in (gs["p"], u["p"]))]
    return verdict[0] != verdict[1]


def _view(snap: dict, game: dict) -> dict | None:
    return betting.view_from_snapshot(snap["games"], game["home"], game["away"],
                                      datetime.fromisoformat(game["tip_utc"]), snap["taken_at"])


def news(changes: list[dict]) -> str:
    """'ATL 的 Trae Young 改成缺陣': the status changes behind a recompute, the players who play the most first."""
    said = "、".join(f"{c['team']} 的 {c['name']} " + ("不在傷兵名單了" if c["after"] is None
                                                     else f"改成{STATUS_ZH.get(c['after'], c['after'])}")
                    for c in changes[:NEWS_SHOWN])
    return said + (f"，共 {len(changes)} 人狀態改變" if len(changes) > NEWS_SHOWN else "")


def why_not(row: dict, side: str) -> str:
    """Why a side advised earlier is not worth a bet any more, at the prices of the moment."""
    price, book = (row.get("best") or {}).get(side) or (None, None)
    if not price:
        return "現在沒有賠率，書商可能暫時撤盤"
    if row.get("suspect") == side:
        return f"模型和賭盤差太多（{digest.model_line(row, side)}），多半是有模型還不知道的消息"
    return f"現在 {price:.2f} @{book}，期望值 {row['ev'][side]:+.1%}"


def message(actions: list[dict], now: datetime) -> tuple[str, str, str]:
    """Subject, text and HTML for one look's changes to the advice: bets newly worth it, and bets no longer."""
    hhmm = f"{now.astimezone(ET):%H:%M}"
    out, bold = [f"【賽前更新 {hhmm}】"], set()
    for a in actions:
        g, side, row = a["game"], a["side"], a["row"]
        bold.add(len(out) + 1)
        out += ["", f"{'新增' if a['kind'] == 'add' else '取消'}　{digest.tip_time(g['tip_utc'])}  {g['away']} @ {g['home']}"]
        if a["kind"] == "add":
            out += digest.bet_lines(row, side) + [f"原因：{news(a['changes'])}；{digest.model_line(row, side)}"]
        else:
            out += [f"{'早上' if side == a['morning'] else '稍早'}推薦的 {side} 不值得投了：{why_not(row, side)}",
                    f"原因：{news(a['changes'])}"]
    out += ["", digest.DISCLAIMER]
    what = "、".join(f"{label} {n} 注" for label, n in (("新增", sum(a["kind"] == "add" for a in actions)),
                                                      ("取消", sum(a["kind"] == "cancel" for a in actions))) if n)
    return f"Fact or Fluke｜賽前更新 {hhmm}｜{what}", "\n".join(out), digest.to_html(out, bold)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _snapshot(key: str, repo: Path, tag: str) -> dict | None:
    """One h2h odds snapshot (1 credit), kept like record_odds.py keeps its own; None if the API refused."""
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
    state = load_state(spath, table, morning_rows(repo, table))
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
    need = {u["game"]["game_id"] for u in updates if may_change(u, state["games"][u["game"]["game_id"]])}
    if need and snap is None and key:
        snap = _snapshot(key, repo, "pre")
    waiting = need if key and snap is None else set()     # prices needed, the API refused: this report again
    actions, rows = [], []
    for u in updates:
        g = u["game"]
        if g["game_id"] in waiting:
            continue
        gs = state["games"][g["game_id"]]
        fresh = snap is not None and g["game_id"] in need
        view = _view(snap, g) if snap is not None and fresh else None
        row = priced(g, u["p"], view)
        old = gs["pick"]
        new = row["pick"] if fresh else old
        if new != old:
            actions += [dict(kind=kind, side=side, game=g, row=row, changes=u["changes"], morning=gs["morning"])
                        for kind, side in (("cancel", old), ("add", new)) if side]
            gs["pick"] = new
        if view:
            gs["view"] = view
        gs["listed"], gs["p"] = u["listed"], u["p"]
        rows.append(_ledger_row(table, u, row, stamp, now, old, new))
    sent = None
    if actions and not dry:
        sent = email.send(*message(actions, now))
        ledger.append(repo / "ledger" / "bets_pregame.jsonl",     # the morning book already holds its own picks
                      [_bet_row(table, a, stamp, now) for a in actions if a["kind"] == "add" and a["side"] != a["morning"]])
    if not dry:
        ledger.append(repo / "ledger" / "pregame.jsonl", rows)
        if not waiting:
            state["stamp"] = stamp
        _write(spath, state)
    return {"report": stamp, "closing": closing, "updates": len(rows), "priced": bool(need) and snap is not None,
            "waiting": sorted(waiting),
            "advice": [f"{a['kind']} {a['side']} ({a['game']['away']}@{a['game']['home']})" for a in actions],
            "email": sent,
            "games": [f"{u['game']['away']}@{u['game']['home']} {u['p_before']:.3f}->{u['p']:.3f}" for u in updates]}


def _bet_row(table: dict, a: dict, stamp: str, now: datetime) -> dict:
    """A bet the watch newly advised, in the evening's own paper book: one per game, the first one counts."""
    g, side, row = a["game"], a["side"], a["row"]
    price, book = row["best"][side]
    return dict(id=f"{g['game_id']}:{table['version']}:pre:bet", made_at=now.isoformat(), kind="pregame",
                model=table["model"], version=table["version"], game_id=g["game_id"], game_date=table["day"],
                tip_utc=g["tip_utc"], home=g["home"], away=g["away"], side="home" if side == g["home"] else "away",
                team=side, price=price, book=book, stake=betting.STAKE, ev=round(row["ev"][side], 4),
                report_stamp=stamp)


def _ledger_row(table: dict, u: dict, row: dict, stamp: str, now: datetime, advice_before, advice) -> dict:
    g = u["game"]
    return dict(id=f"{g['game_id']}:{table['version']}:pre:{now.astimezone(ET):%H%M}", made_at=now.isoformat(),
                kind="pregame", model=table["model"], version=table["version"], game_id=g["game_id"],
                game_date=table["day"], tip_utc=g["tip_utc"], home=g["home"], away=g["away"],
                p_home=round(u["p"], 4), p_morning=g["p_home"], p_before=round(u["p_before"], 4),
                report=round(u["x"], 3), report_stamp=stamp,
                changes=[{k: c[k] for k in ("team", "player", "name", "before", "after")} for c in u["changes"]],
                advice_before=advice_before, advice=advice, pushed=advice != advice_before,
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
    line = "今天早上的資料沒有上傳，多半是筆電早上沒跑完；今晚不會有賽前更新。"
    sent = email.send(f"Fact or Fluke｜{day.month}/{day.day} 早上沒跑完", line, digest.to_html([line]))
    _write(spath, {"alerted": True})
    return {"alert": sent}

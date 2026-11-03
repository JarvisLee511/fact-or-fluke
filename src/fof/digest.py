"""The daily email: only the games worth a paper bet (D3), each with its best price, the lowest price still
worth it and a short reason; a day without one says so in one line. Everything else (the other games, the
scorecard, the fun facts) is on the site. Chinese sentences, English names, plain text plus HTML."""
from __future__ import annotations

import html
from collections.abc import Container
from datetime import date, datetime

from .betting import VALUE_EDGE
from .config import ET

WEEKDAY = "一二三四五六日"
DISCLAIMER = "這是分析和娛樂，不是投資建議。"
# each part of the model's number (player.predict's `why`) said plainly, for the side it helps (t) over the other (o)
PLAIN = {"players": "{t} 陣容實力較強", "absent": "{o} 傷兵影響較大", "elo": "{t} 戰績較好", "home": "{t} 主場",
         "schedule": "賽程對 {t} 有利", "b2b": "{o} 背靠背", "rest": "{t} 休息較多", "tif": "{o} 4 天 3 戰"}


def tip_time(tip_utc) -> str:
    """'19:30': the tip in ET."""
    t = tip_utc if isinstance(tip_utc, datetime) else datetime.fromisoformat(str(tip_utc))
    if t.tzinfo is None:
        from zoneinfo import ZoneInfo
        t = t.replace(tzinfo=ZoneInfo("UTC"))
    return t.astimezone(ET).strftime("%H:%M")


def side_p(p_home: float, row: dict, side: str) -> float:
    return p_home if side == row["home"] else 1 - p_home


def min_price(p: float, price: float) -> float:
    """The lowest price at which a side the model gives probability p still clears the edge (D3), to the cent
    and never above the price on offer."""
    return min(round((1 + VALUE_EDGE) / p, 2), price)


def plain_reasons(row: dict, side: str, top: int = 2) -> str:
    """'CHI 主場、ATL 傷兵影響較大': the biggest parts of the model's number that favour `side`."""
    other, sign = (row["away"], 1) if side == row["home"] else (row["home"], -1)
    parts = sorted(((k, v * sign) for k, v in (row.get("why") or {}).items() if v * sign >= 0.01), key=lambda kv: -kv[1])
    return "、".join((PLAIN[k] if k in PLAIN else k + " {t}").format(t=side, o=other) for k, _ in parts[:top])


def model_line(row: dict, side: str) -> str:
    """'模型 CHI 51%、賭盤 46%': both probabilities for the side."""
    out = f"模型 {side} {side_p(row['p_home'], row, side):.0%}"
    if row.get("market_p_home") is not None:
        out += f"、賭盤 {side_p(row['market_p_home'], row, side):.0%}"
    return out


def bet_lines(row: dict, side: str) -> list[str]:
    """The lines under a pick: what to take where, the lowest price still worth it."""
    price, book = row["best"][side]
    return [f"投 {side}：{price:.2f} @{book}，期望值 {row['ev'][side]:+.1%}",
            f"賠率低於 {min_price(side_p(row['p_home'], row, side), price):.2f} 就不值得投"]


def to_html(lines: list[str], bold: Container[int] = ()) -> str:
    """The email's HTML: one div per line, the lines at `bold` in bold."""
    cells = []
    for i, line in enumerate(lines):
        text = html.escape(line) or "&nbsp;"
        cells.append(f"<div><b>{text}</b></div>" if i in bold else f"<div>{text}</div>")
    body = "".join(cells)
    return ('<div style="font-family:\'Microsoft JhengHei\',\'PingFang TC\',sans-serif;font-size:15px;'
            f'line-height:1.6;color:#1f2328">{body}</div>')


def compose(day: date, preds: list[dict], site_url: str | None = None) -> tuple[str, str, str]:
    """Subject, text and HTML for the morning: the ledger's picks of the day, or one line saying there are none."""
    title = f"Fact or Fluke｜{day.month}/{day.day}（{WEEKDAY[day.weekday()]}）"
    picks = [p for p in preds if p.get("pick")]
    unpriced = [p for p in preds if not any(v and v[0] for v in (p.get("best") or {}).values())]
    if not preds:
        head = subject = "今天沒有比賽"
    elif len(unpriced) == len(preds):
        head, subject = "今天抓不到賠率，沒辦法判斷哪幾場值得投。", "今天抓不到賠率"
    elif picks:
        head = subject = f"今天 {len(picks)} 注"
    else:
        head = subject = "今天沒有值得投注的比賽"
    out, bold = [title, "", head], set()
    for p in picks:
        side, why = p["pick"], plain_reasons(p, p["pick"])
        bold.add(len(out) + 1)
        out += ["", f"{tip_time(p['tip_utc'])}  {p['away']} @ {p['home']}", *bet_lines(p, side),
                f"原因：{model_line(p, side)}" + (f"；{why}" if why else "")]
    if unpriced and len(unpriced) < len(preds):
        out += ["", f"另有 {len(unpriced)} 場還沒有賠率，沒辦法判斷。"]
    if site_url:
        out += ["", f"→ 詳細：{site_url}"]
    out += ["", DISCLAIMER]
    return f"{title} {subject}", "\n".join(out), to_html(out, bold)

"""The daily email: today's predictions first (the part read every morning), then the scorecard, the
standings changes and last night's records. Chinese sentences, English names, plain text plus HTML."""
from __future__ import annotations

import html
from datetime import date, datetime

from .config import ET

WEEKDAY = "一二三四五六日"


def _tip(tip_utc) -> str:
    t = tip_utc if isinstance(tip_utc, datetime) else datetime.fromisoformat(str(tip_utc))
    if t.tzinfo is None:
        from zoneinfo import ZoneInfo
        t = t.replace(tzinfo=ZoneInfo("UTC"))
    return t.astimezone(ET).strftime("%H:%M")


def prediction_lines(p: dict) -> list[str]:
    home, away, ph = p["home"], p["away"], p["p_home"]
    fav, pf = (home, ph) if ph >= 0.5 else (away, 1 - ph)
    head = f"{_tip(p['tip_utc'])}  {away} @ {home}"
    mkt = p.get("market_p_home")
    model = f"  模型：{fav} {pf:.0%}"
    if mkt is not None:
        mfav, mp = (home, mkt) if mkt >= 0.5 else (away, 1 - mkt)
        model += f"｜賭盤：{mfav} {mp:.0%}"
    lines = [head, model]
    best, ev, pick, suspect = p.get("best"), p.get("ev"), p.get("pick"), p.get("suspect")
    if pick:
        price, book = best[pick]
        lines.append(f"  ★ 划算：{pick} {price:.2f} @{book}（期望值 {ev[pick]:+.1%}）")
    elif suspect:
        lines.append(f"  模型和賭盤差太多（{suspect} 期望值 {ev[suspect]:+.1%}），多半是模型還不知道的消息，例如傷兵，這注不算")
    elif best and best.get(fav) and best[fav][0]:
        price, book = best[fav]
        lines.append(f"  沒有划算的注（{fav} 最佳 {price:.2f} @{book}，期望值 {ev[fav]:+.1%}）")
    else:
        lines.append("  還沒有賠率")
    return lines


def compose(day: date, preds: list[dict], card: dict, changes: dict, listed_total: int, records: list[dict],
            partial: bool, site_url: str | None = None) -> tuple[str, str, str]:
    title = f"Fact or Fluke｜{day.month}/{day.day}（{WEEKDAY[day.weekday()]}）"
    out = [title, ""]
    if partial:
        out += ["※ 昨晚的追蹤數據到中午還沒出來，今天的 fun fact 用的是前一天的累計資料。", ""]
    out.append(f"今日預測（{len(preds)} 場，基準模型：Elo＋賽程情境）" if preds else "今天沒有比賽。")
    for p in preds:
        out += prediction_lines(p)
    y = card.get("yesterday") or {}
    out += [""]
    if y.get("n"):
        market = f"、賭盤熱門 {y['market_correct']}/{y['market_n']}" if y.get("market_n") else ""
        out.append(f"昨天：模型猜中 {y['model_correct']}/{y['n']}{market}")
    b = card.get("bets") or {}
    if b.get("n"):
        out.append(f"模擬帳本：本季 {b['profit']:+.2f}u（稅後 {b['profit_after_tax']:+.2f}u），"
                   f"{b['n']} 注 {b['wins']} 勝")
    else:
        out.append("模擬帳本：還沒有結算的注")
    out.append(f"排行榜：新上榜 {changes.get('new_listed', 0)}、淘汰 {changes.get('eliminated', 0)}"
               f"（本季上榜 {listed_total} 則）")
    if records:
        out += ["", "昨晚紀錄："] + [f"• {r['text_zh']}" for r in records]
    if site_url:
        out += ["", f"→ 詳細：{site_url}"]
    out += ["", "這是分析和娛樂，不是投資建議。"]
    text = "\n".join(out)
    body = "".join(f"<div>{html.escape(line) or '&nbsp;'}</div>" for line in out)
    html_doc = ('<div style="font-family:\'Microsoft JhengHei\',\'PingFang TC\',sans-serif;font-size:15px;'
                f'line-height:1.6;color:#1f2328">{body}</div>')
    return title + f" 今日 {len(preds)} 場", text, html_doc

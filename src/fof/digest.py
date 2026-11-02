"""The daily email: today's predictions first (the part read every morning), then the scorecard and the fun
facts last night's games put on the standings or overturned. Chinese sentences, English names, plain text plus
HTML."""
from __future__ import annotations

import html
from datetime import date, datetime

from .config import ET

WEEKDAY = "一二三四五六日"
REASON = {"players": "球員實力", "absent": "傷兵缺陣", "elo": "Elo 戰績", "home": "主場", "schedule": "賽程休息",
          "b2b": "背靠背", "rest": "休息天數", "tif": "4 天 3 戰"}


def _tip(tip_utc) -> str:
    t = tip_utc if isinstance(tip_utc, datetime) else datetime.fromisoformat(str(tip_utc))
    if t.tzinfo is None:
        from zoneinfo import ZoneInfo
        t = t.replace(tzinfo=ZoneInfo("UTC"))
    return t.astimezone(ET).strftime("%H:%M")


def _md(day: str) -> str:
    """'2026-11-02' -> '11/2'."""
    return f"{int(day[5:7])}/{int(day[8:10])}"


def reasons(p: dict) -> str:
    """'球員實力 BOS +8、主場 BOS +4': each part's share of the win probability (points), biggest first."""
    parts = sorted(((k, v) for k, v in (p.get("why") or {}).items() if abs(v) >= 0.005), key=lambda kv: -abs(kv[1]))
    return "、".join(f"{REASON.get(k, k)} {p['home'] if v > 0 else p['away']} +{int(abs(v) * 100 + 0.5)}"
                    for k, v in parts)


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
    why = reasons(p)
    if why:
        lines.append(f"  原因：{why}")
    return lines + [f"  {value_line(p)}"]


def value_line(p: dict) -> str:
    """The paper-bet verdict for a prediction: a value pick, a disagreement too big to trust, the favourite's
    best price, or no odds yet."""
    fav = p["home"] if p["p_home"] >= 0.5 else p["away"]
    best, ev, pick, suspect = p.get("best"), p.get("ev"), p.get("pick"), p.get("suspect")
    if pick:
        price, book = best[pick]
        return f"★ 划算：{pick} {price:.2f} @{book}（期望值 {ev[pick]:+.1%}）"
    if suspect:
        return f"模型和賭盤差太多（{suspect} 期望值 {ev[suspect]:+.1%}），多半是模型還不知道的消息，例如傷兵，這注不算"
    if best and best.get(fav) and best[fav][0]:
        price, book = best[fav]
        return f"沒有划算的注（{fav} 最佳 {price:.2f} @{book}，期望值 {ev[fav]:+.1%}）"
    return "還沒有賠率"


def compose(day: date, preds: list[dict], card: dict, changes: dict, listed_total: int, night: dict,
            partial: bool, site_url: str | None = None) -> tuple[str, str, str]:
    title = f"Fact or Fluke｜{day.month}/{day.day}（{WEEKDAY[day.weekday()]}）"
    out = [title, ""]
    if partial:
        out += ["※ 昨晚的追蹤數據到中午還沒出來，今天的 fun fact 用的是前一天的累計資料。", ""]
    out.append(f"今日預測（{len(preds)} 場，模型：{card.get('label', '')}）" if preds else "今天沒有比賽。")
    for p in preds:
        out += prediction_lines(p)
    y = card.get("yesterday") or {}
    out += [""]
    if y.get("n"):
        market = f"、賭盤熱門 {y['market_correct']}/{y['market_n']}" if y.get("market_n") else ""
        out.append(f"昨天：模型猜中 {y['model_correct']}/{y['n']}{market}")
    for old in card.get("previous") or []:   # the day after a switch: yesterday was the old model's, scored apart
        oy, ob = old.get("yesterday") or {}, old.get("bets") or {}
        if oy.get("n"):
            market = f"、賭盤熱門 {oy['market_correct']}/{oy['market_n']}" if oy.get("market_n") else ""
            out.append(f"昨天（舊版模型：{old['label']}）：猜中 {oy['model_correct']}/{oy['n']}{market}")
            if ob.get("n"):
                span = _md(old["since"]) + ("" if old["until"] == old["since"] else f"–{_md(old['until'])}")
                out.append(f"舊版模擬帳本（{span}）：{ob['profit']:+.2f}u（稅後 {ob['profit_after_tax']:+.2f}u），"
                           f"{ob['n']} 注 {ob['wins']} 勝，之後分開計")
    b = card.get("bets") or {}
    since = f"{_md(card['since'])} 起 " if card.get("since") else ""
    if b.get("n"):
        out.append(f"模擬帳本：{since}{b['profit']:+.2f}u（稅後 {b['profit_after_tax']:+.2f}u），"
                   f"{b['n']} 注 {b['wins']} 勝")
    else:
        out.append("模擬帳本：還沒有結算的注")
    listed, overturned = night.get("listed") or [], night.get("eliminated") or []
    out.append(f"排行榜：新上榜 {len(listed)}、被推翻 {len(overturned)}"
               f"（本季上榜 {listed_total} 則、Fluke 判決 {changes.get('fluke', 0)} 則）")
    for label, facts in (("新上榜", listed), ("被推翻", overturned)):
        if facts:
            out += ["", f"{label}："] + [f"• {f['text_zh']}" for f in facts]
    if site_url:
        out += ["", f"→ 詳細：{site_url}"]
    out += ["", "這是分析和娛樂，不是投資建議。"]
    text = "\n".join(out)
    body = "".join(f"<div>{html.escape(line) or '&nbsp;'}</div>" for line in out)
    html_doc = ('<div style="font-family:\'Microsoft JhengHei\',\'PingFang TC\',sans-serif;font-size:15px;'
                f'line-height:1.6;color:#1f2328">{body}</div>')
    return title + f" 今日 {len(preds)} 場", text, html_doc

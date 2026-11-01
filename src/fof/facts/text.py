"""Bilingual sentences for fun facts. Player and team names stay in English in both languages."""
from __future__ import annotations

TOUCH_ZH = {"elbow": "肘區", "post": "低位", "paint": "禁區"}
TOUCH_EN = {"elbow": "elbow touches", "post": "post touches", "paint": "paint touches", "drive": "drives"}
ZONE_ZH = {"rim": "籃下", "mid": "中距離"}
ZONE_EN = {"rim": "at the rim", "mid": "from mid-range"}
QUARTER_ZH = {1: "一", 2: "二", 3: "三", 4: "四"}
QUARTER_EN = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th"}
PEERS_ZH, PEERS_EN = "同類型球員平均", "players in a similar role:"
KIND = {  # the groups the standings take turns between and filter by
    "style": ("投籃方式", "Shot style"),
    "touch": ("拿球之後", "Touches"),
    "partner": ("搭檔", "Partners"),
    "corner": ("底角", "Corners"),
    "contest": ("貼身防守", "Tight defense"),
    "zone": ("出手區域", "Shot zones"),
    "clutch": ("關鍵時刻", "Clutch"),
    "ft": ("罰球", "Free throws"),
    "side": ("左右邊", "Left vs right"),
    "home": ("主客場", "Home vs away"),
    "half": ("上下半場", "Halves"),
    "b2b": ("背靠背", "Back-to-backs"),
    "quarter": ("各節", "Quarters"),
    "hot": ("手感", "Hot hand"),
}
UNIT = {  # what n counts, for the "based on N ..." line
    "pass_3p": ("次接球後的三分出手", "3-point attempts after those passes"),
    "pass_fg": ("次接球後的出手", "shots after those passes"),
    "ast_partner": ("次助攻", "assists"),
    "cs_share": ("次三分出手", "3-point attempts"),
    "pullup_3p": ("次運球急停三分", "pull-up threes"),
    "tight_fg": ("次被貼身防守的出手", "tightly contested shots"),
    "corner_side": ("次底角三分", "corner threes"),
    "corner_3p": ("次底角三分", "corner threes"),
    "clutch_usage": ("次全隊關鍵時刻出手", "team clutch shots"),
    "clutch_fg": ("次關鍵時刻出手", "clutch shots"),
    "ft_2nd": ("次第二球罰球", "second free throws"),
    "side_3p": ("次左邊三分", "threes from the left"),
    "home_3p": ("次主場三分", "home threes"),
    "home_fg": ("次主場出手", "home shots"),
    "half_fg": ("次下半場出手", "second-half shots"),
    "b2b_fg": ("次背靠背第二天的出手", "shots on second nights of back-to-backs"),
    "b2b_team": ("場背靠背第二天", "second nights of back-to-backs"),
    "hot_hand": ("次投進後的下一球", "shots right after a make"),
}
CLUTCH_ZH = "關鍵時刻＝第四節或延長賽最後 5 分鐘、分差 5 分內"
CLUTCH_EN = "clutch = last 5 minutes of the 4th quarter or overtime, within 5 points"


def pct(x: float) -> str:
    return f"{x:.0%}"


def sentence(c: dict) -> tuple[str, str]:
    fam, d = c["family"], c["detail"]
    s, k, n, rate, base = c["subject"], c["k"], c["n"], pct(c["k"] / c["n"]), pct(c["p0"])
    up = c["k"] / c["n"] > c["p0"]
    if fam == "pass_3p":
        return (f"{s} 接 {d['passer']} 的傳球投三分 {k}/{n}（{rate}），接其他隊友的傳球是 {base}",
                f"{s} hits {rate} of threes off {d['passer']}'s passes ({k}/{n}), vs {base} off other teammates")
    if fam == "pass_fg":
        return (f"{s} 接 {d['passer']} 的傳球後出手 {k}/{n}（{rate}），接其他隊友的傳球是 {base}",
                f"{s} shoots {rate} after {d['passer']}'s passes ({k}/{n}), vs {base} after other teammates'")
    if fam == "ast_partner":
        r = d["receiver"]
        return (f"{s} 的助攻有 {rate} 是傳給 {r}（{k}/{n}），其他隊友的助攻只有 {base} 給他",
                f"{rate} of {s}'s assists go to {r} ({k}/{n}); other teammates send him {base} of theirs")
    if fam.startswith("touch_"):
        t = d["touch"]
        shoot = fam.startswith("touch_shoot")
        if t == "drive":
            zh = f"{s} 切入後 {rate} 會{'自己出手' if shoot else '傳出去'}（{PEERS_ZH} {base}）"
            en = f"{s} {'shoots' if shoot else 'passes'} on {rate} of drives ({PEERS_EN} {base})"
        else:
            zh = f"{s} 在{TOUCH_ZH[t]}拿到球，{rate} 會{'直接出手' if shoot else '傳出去'}（{PEERS_ZH} {base}）"
            en = f"{s} {'shoots' if shoot else 'passes'} on {rate} of {TOUCH_EN[t]} ({PEERS_EN} {base})"
        return zh, en
    if fam == "cs_share":
        return (f"{s} 的三分有 {rate} 是接球就投（{PEERS_ZH} {base}）",
                f"{rate} of {s}'s threes are catch-and-shoot ({PEERS_EN} {base})")
    if fam == "pullup_3p":
        return ((f"{s} 運球急停三分 {k}/{n}（{rate}），比接球投的 {base} 還準" if up else
                 f"{s} 運球急停三分只有 {k}/{n}（{rate}），接球投卻有 {base}"),
                (f"{s} makes {rate} of pull-up threes ({k}/{n}), better than {base} on catch-and-shoot" if up else
                 f"{s} makes only {rate} of pull-up threes ({k}/{n}), vs {base} on catch-and-shoot"))
    if fam == "tight_fg":
        return ((f"{s} 被貼身（2 呎內）防守還能投 {rate}（{PEERS_ZH} {base}）" if up else
                 f"{s} 一被貼身（2 呎內）防守，命中率掉到 {rate}（{PEERS_ZH} {base}）"),
                (f"{s} shoots {rate} even with a defender within 2 ft ({PEERS_EN} {base})" if up else
                 f"{s} drops to {rate} with a defender within 2 ft ({PEERS_EN} {base})"))
    if fam == "corner_side":
        side_share = c["k"] / c["n"] if up else 1 - c["k"] / c["n"]
        zh_side, en_side = ("左", "left") if up else ("右", "right")
        return (f"{s} 的底角三分有 {pct(side_share)} 都在{zh_side}底角（聯盟平均 {pct(c['p0'] if up else 1 - c['p0'])}）",
                f"{pct(side_share)} of {s}'s corner threes come from the {en_side} corner "
                f"(league {pct(c['p0'] if up else 1 - c['p0'])})")
    if fam == "corner_3p":
        return ((f"{s} 底角三分 {k}/{n}（{rate}），弧頂一帶只有 {base}" if up else
                 f"{s} 底角三分只有 {k}/{n}（{rate}），弧頂一帶反而有 {base}"),
                (f"{s} hits {rate} from the corners ({k}/{n}) but {base} above the break" if up else
                 f"{s} hits only {rate} from the corners ({k}/{n}) vs {base} above the break"))
    if fam.startswith("zone_fg"):
        zh_z, en_z = ZONE_ZH[d["zone"]], ZONE_EN[d["zone"]]
        return ((f"{s} 在{zh_z}命中率 {rate}（{k}/{n}），{PEERS_ZH}只有 {base}" if up else
                 f"{s} 在{zh_z}只投進 {rate}（{k}/{n}），{PEERS_ZH}有 {base}"),
                (f"{s} makes {rate} {en_z} ({k}/{n}); {PEERS_EN} {base}" if up else
                 f"{s} makes only {rate} {en_z} ({k}/{n}); {PEERS_EN} {base}"))
    if fam == "clutch_usage":
        return (f"{s} 在關鍵時刻投了全隊 {rate} 的球（{k}/{n}），其他時間只投 {base}",
                f"{s} takes {rate} of his team's clutch shots ({k}/{n}), vs {base} of the rest")
    if fam == "clutch_fg":
        own = pct(d["own"])
        return ((f"{s} 關鍵時刻命中率 {rate}（{k}/{n}），其他時間 {own}" if up else
                 f"{s} 關鍵時刻命中率掉到 {rate}（{k}/{n}），其他時間 {own}"),
                (f"{s} shoots {rate} in the clutch ({k}/{n}), {own} the rest of the time" if up else
                 f"{s} drops to {rate} in the clutch ({k}/{n}), from {own} the rest of the time"))
    if fam == "ft_2nd":
        return ((f"{s} 罰球第二球命中率 {rate}（{k}/{n}），第一球只有 {base}" if up else
                 f"{s} 罰球第一球命中率 {base}，第二球反而只有 {rate}（{k}/{n}）"),
                (f"{s} makes {rate} of second free throws ({k}/{n}) but only {base} of first ones" if up else
                 f"{s} makes {base} of first free throws but only {rate} of second ones ({k}/{n})"))
    if fam == "side_3p":
        return ((f"{s} 從左邊投三分 {rate}（{k}/{n}），右邊只有 {base}" if up else
                 f"{s} 從左邊投三分只有 {rate}（{k}/{n}），右邊有 {base}"),
                (f"{s} hits {rate} of threes from the left ({k}/{n}) but {base} from the right" if up else
                 f"{s} hits only {rate} of threes from the left ({k}/{n}) vs {base} from the right"))
    if fam in ("home_3p", "home_fg"):
        zh_w, en_w = ("三分", "threes") if fam == "home_3p" else ("命中率", "shots")
        return ((f"{s} 主場{zh_w} {rate}（{k}/{n}），客場只有 {base}" if up else
                 f"{s} 主場{zh_w}只有 {rate}（{k}/{n}），客場反而有 {base}"),
                (f"{s} makes {rate} of home {en_w} ({k}/{n}) but {base} on the road" if up else
                 f"{s} makes only {rate} of home {en_w} ({k}/{n}) vs {base} on the road"))
    if fam == "half_fg":
        return ((f"{s} 下半場命中率 {rate}（{k}/{n}），上半場只有 {base}" if up else
                 f"{s} 上半場命中率 {base}，下半場掉到 {rate}（{k}/{n}）"),
                (f"{s} shoots {rate} after halftime ({k}/{n}), {base} before it" if up else
                 f"{s} shoots {base} before halftime but {rate} after it ({k}/{n})"))
    if fam == "b2b_fg":
        return ((f"{s} 背靠背第二天命中率反而有 {rate}（{k}/{n}），平常 {base}" if up else
                 f"{s} 背靠背第二天命中率掉到 {rate}（{k}/{n}），平常 {base}"),
                (f"{s} shoots {rate} on second nights of back-to-backs ({k}/{n}), {base} otherwise" if up else
                 f"{s} drops to {rate} on second nights of back-to-backs ({k}/{n}), from {base} otherwise"))
    if fam == "b2b_team":
        return (f"{s} 背靠背第二天 {k} 勝 {n - k} 敗（{rate}），其他比賽勝率 {base}",
                f"{s} are {k}-{n - k} ({rate}) on second nights of back-to-backs, {base} in other games")
    if fam == "quarter_team":
        q = d["quarter"]
        return ((f"{s} 第{QUARTER_ZH[q]}節贏了 {k} 場、輸 {n - k} 場（{rate}），其他節只贏 {base}" if up else
                 f"{s} 第{QUARTER_ZH[q]}節最容易崩：只贏 {k} 場、輸 {n - k} 場（{rate}），其他節贏 {base}"),
                (f"{s} win the {QUARTER_EN[q]} quarter {k}-{n - k} ({rate}), other quarters {base}" if up else
                 f"{s} win the {QUARTER_EN[q]} quarter only {k}-{n - k} ({rate}), other quarters {base}"))
    if fam == "hot_hand":
        return ((f"{s} 投進之後的下一球命中率 {rate}（{k}/{n}），投丟之後只有 {base}" if up else
                 f"{s} 投進之後的下一球反而只有 {rate}（{k}/{n}），投丟之後有 {base}"),
                (f"{s} makes {rate} of shots right after a make ({k}/{n}), {base} right after a miss" if up else
                 f"{s} makes only {rate} of shots right after a make ({k}/{n}), {base} right after a miss"))
    raise KeyError(fam)


def basis(c: dict, season_label: str) -> tuple[str, str]:
    fam, d = c["family"].split(":")[0], c["detail"]
    if fam.startswith("touch_"):
        t = d["touch"]
        zh_unit = "次切入" if t == "drive" else f"次{TOUCH_ZH[t]}拿球"
        en_unit = TOUCH_EN[t]
    elif fam == "zone_fg":
        zh_unit, en_unit = f"次{ZONE_ZH[d['zone']]}出手", f"shots {ZONE_EN[d['zone']]}"
    elif fam == "quarter_team":
        zh_unit, en_unit = f"場分出勝負的第{QUARTER_ZH[d['quarter']]}節", f"decided {QUARTER_EN[d['quarter']]} quarters"
    else:
        zh_unit, en_unit = UNIT[fam]
    zh = f"根據 {c['n']} {zh_unit}（{season_label} 例行賽）"
    en = f"Based on {c['n']} {en_unit} ({season_label} regular season)"
    if d.get("peers"):
        zh += f"；同類型：{'、'.join(d['peers'][:2])} 等 30 人"
        en += f"; similar role: {', '.join(d['peers'][:2])} and 28 more"
    if fam in ("clutch_usage", "clutch_fg"):
        zh += f"；{CLUTCH_ZH}"
        en += f"; {CLUTCH_EN}"
    if fam == "clutch_fg":
        zh += f"，全聯盟這時命中率 {pct(d['league_other'])}→{pct(d['league_clutch'])}，已算進去"
        en += f"; the league drops {pct(d['league_other'])}→{pct(d['league_clutch'])} then (allowed for)"
    return zh, en


def verdict(c: dict, status: str) -> tuple[str, str]:
    """For a situation split: how rare a gap this big is by luck alone, against how many were scanned. A Fluke
    is one that luck alone hands out at least once among that many."""
    fam = c["family"]
    zh_w, en_w = ("隊", "teams") if fam == "b2b_team" else ("組", "team-quarters") if fam == "quarter_team" \
        else ("人", "players")
    n, p = c["scanned"], c["luck"] / c["scanned"]
    every = 1 / p if p > 0 else float("inf")
    x_zh, x_en = (f"{round(every):,}", f"{round(every):,}") if every < 1e6 else ("超過 100 萬", "over a million")
    scanned_zh = f"這次掃過 {n} {zh_w}" + ("（球隊 × 節次）" if fam == "quarter_team" else "")
    if status == "fluke":
        return (f"光靠運氣，每 {x_zh} {zh_w}就會有 1 {zh_w}差這麼多，{scanned_zh}",
                f"Luck alone gives 1 in {x_en} {en_w} a gap this big, and {n} were scanned")
    watch = ("，值得觀察", ": worth watching") if status == "observing" else ("", "")
    return (f"光靠運氣，每 {x_zh} {zh_w}才會有 1 {zh_w}差這麼多，{scanned_zh}{watch[0]}",
            f"Luck alone gives only 1 in {x_en} {en_w} a gap this big ({n} scanned){watch[1]}")

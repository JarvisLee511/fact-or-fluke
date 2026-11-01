"""Bilingual sentences for fun facts. Player and team names stay in English in both languages."""
from __future__ import annotations

POS_ZH = {"G": "後衛", "F": "前鋒", "C": "中鋒", "?": "同位置"}
POS_EN = {"G": "guards", "F": "forwards", "C": "centers", "?": "peers"}
TOUCH_ZH = {"elbow": "肘區", "post": "低位", "paint": "禁區"}
TOUCH_EN = {"elbow": "elbow touches", "post": "post touches", "paint": "paint touches", "drive": "drives"}
UNIT = {  # what n counts, for the "based on N ..." line
    "pass_3p": ("次接球後的三分出手", "3-point attempts after those passes"),
    "pass_fg": ("次接球後的出手", "shots after those passes"),
    "cs_share": ("次三分出手", "3-point attempts"),
    "pullup_3p": ("次運球急停三分", "pull-up threes"),
    "tight_fg": ("次被貼身防守的出手", "tightly contested shots"),
    "corner_side": ("次底角三分", "corner threes"),
    "corner_3p": ("次底角三分", "corner threes"),
}


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
    if fam.startswith("touch_"):
        t, pos_zh, pos_en = d["touch"], POS_ZH[d["pos"]], POS_EN[d["pos"]]
        shoot = fam.startswith("touch_shoot")
        if t == "drive":
            zh = f"{s} 切入後 {rate} 會{'自己出手' if shoot else '傳出去'}（{pos_zh}平均 {base}）"
            en = f"{s} {'shoots' if shoot else 'passes'} on {rate} of drives ({pos_en} average {base})"
        else:
            zh = f"{s} 在{TOUCH_ZH[t]}拿到球，{rate} 會{'直接出手' if shoot else '傳出去'}（{pos_zh}平均 {base}）"
            en = f"{s} {'shoots' if shoot else 'passes'} on {rate} of {TOUCH_EN[t]} ({pos_en} average {base})"
        return zh, en
    if fam == "cs_share":
        return (f"{s} 的三分有 {rate} 是接球就投（{POS_ZH[d['pos']]}平均 {base}）",
                f"{rate} of {s}'s threes are catch-and-shoot ({POS_EN[d['pos']]} average {base})")
    if fam == "pullup_3p":
        return ((f"{s} 運球急停三分 {k}/{n}（{rate}），比接球投的 {base} 還準" if up else
                 f"{s} 運球急停三分只有 {k}/{n}（{rate}），接球投卻有 {base}"),
                (f"{s} makes {rate} of pull-up threes ({k}/{n}), better than {base} on catch-and-shoot" if up else
                 f"{s} makes only {rate} of pull-up threes ({k}/{n}), vs {base} on catch-and-shoot"))
    if fam == "tight_fg":
        pos_zh, pos_en = POS_ZH[d["pos"]], POS_EN[d["pos"]]
        return ((f"{s} 被貼身（2 呎內）防守還能投 {rate}（{pos_zh}平均 {base}）" if up else
                 f"{s} 一被貼身（2 呎內）防守，命中率掉到 {rate}（{pos_zh}平均 {base}）"),
                (f"{s} shoots {rate} even with a defender within 2 ft ({pos_en} average {base})" if up else
                 f"{s} drops to {rate} with a defender within 2 ft ({pos_en} average {base})"))
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
    raise KeyError(fam)


def basis(c: dict, season_label: str) -> tuple[str, str]:
    fam = c["family"].split(":")[0]
    if fam.startswith("touch_"):
        t = c["detail"]["touch"]
        zh_unit = "次切入" if t == "drive" else f"次{TOUCH_ZH[t]}拿球"
        en_unit = TOUCH_EN[t]
    else:
        zh_unit, en_unit = UNIT[fam]
    return (f"根據 {c['n']} {zh_unit}（{season_label} 例行賽）",
            f"Based on {c['n']} {en_unit} ({season_label} regular season)")

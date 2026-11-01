"""NBA official injury report: the league publishes a PDF every 15 minutes (old ones stay hosted).

Layout facts the parser relies on (checked on the 2026-27 PDFs):
- seven columns whose header words fix the x positions; only page 1 has the header row;
- game date / time / matchup / team appear only on the first row of their group (forward-fill);
- a reason that wraps onto two lines is centred on its player's row, one line above and one below;
- a reason cut by a page break continues at the top of the next page, well above its first row;
- teams that have not filed show "NOT YET SUBMITTED" in the reason column.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

from ..config import ET
from .http import fetch

PDF_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_{stamp}.pdf"
SEASON_PAGE = "https://official.nba.com/nba-injury-report-{season}-season/"
LINK_RE = re.compile(r"Injury-Report_(\d{4}-\d{2}-\d{2}_\d{2}_\d{2}[AP]M)\.pdf")
STAMP_FMT = "%Y-%m-%d_%I_%M%p"

COLUMNS = ["game_date", "game_time", "matchup", "team", "player", "status", "reason"]
CONTEXT = ["game_date", "game_time", "matchup", "team"]
NOT_SUBMITTED = "NOT YET SUBMITTED"
CONT_GAP = 12.0  # a reason line further than this above a page's first row is a carry-over from the last page

TEAM_TRICODE = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "LA Clippers": "LAC", "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def stamp_time(stamp: str) -> datetime:
    """'2026-11-01_12_45AM' -> aware ET datetime."""
    return datetime.strptime(stamp, STAMP_FMT).replace(tzinfo=ET)


def stamp_of(t: datetime) -> str:
    return t.astimezone(ET).strftime(STAMP_FMT)


def latest_stamps(season: str) -> list[str]:
    """Report stamps currently linked from the season page (the page lists only the newest few)."""
    html = fetch(SEASON_PAGE.format(season=season), {"Accept": "text/html,*/*"}).decode("utf-8", "replace")
    return sorted(set(LINK_RE.findall(html)), key=stamp_time)


def download(stamp: str) -> bytes:
    return fetch(PDF_URL.format(stamp=stamp), {"Accept": "application/pdf,*/*"})


def _column_starts(header: list[dict]) -> list[float] | None:
    texts = [w["text"] for w in header]
    try:
        games = [w["x0"] for w in header if w["text"] == "Game"]
        pick = {t: next(w["x0"] for w in header if w["text"] == t) for t in ("Matchup", "Team", "Player", "Current", "Reason")}
    except StopIteration:
        return None
    if len(games) < 2 or "Status" not in texts:
        return None
    return [games[0], games[1], pick["Matchup"], pick["Team"], pick["Player"], pick["Current"], pick["Reason"]]


def _lines(words: list[dict], starts: list[float], tol: float = 1.5) -> list[tuple[float, dict]]:
    """Group words into visual lines, then into column cells."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    out = []
    for ws in lines:
        cells: dict[str, list[str]] = {}
        for w in sorted(ws, key=lambda w: w["x0"]):
            col = max((i for i, s in enumerate(starts) if w["x0"] >= s - 3), default=0)
            cells.setdefault(COLUMNS[col], []).append(w["text"])
        out.append((ws[0]["top"], {k: " ".join(v) for k, v in cells.items()}))
    return out


def _is_furniture(cells: dict) -> bool:
    text = " ".join(cells.values()).strip()
    return bool(re.fullmatch(r"Page \d+ of \d+", text)) or text.startswith("Injury Report:")


def _is_anchor(cells: dict) -> bool:
    return bool(cells.get("player") or cells.get("status")) or NOT_SUBMITTED in " ".join(cells.values()).upper()


def parse_words(pages: list[list[dict]]) -> list[dict]:
    """pages: pdfplumber words per page. Returns one dict per player row (or 'not yet submitted' team row)."""
    rows: list[dict] = []
    carry = {k: "" for k in CONTEXT}
    starts: list[float] | None = None
    for words in pages:
        header_top = next((w["top"] for w in words if w["text"] == "Reason" and any(
            v["text"] == "Matchup" and abs(v["top"] - w["top"]) < 2 for v in words)), None)
        body = words
        if header_top is not None:
            starts = _column_starts([w for w in words if abs(w["top"] - header_top) < 2]) or starts
            body = [w for w in words if w["top"] > header_top + 5]
        if starts is None:
            continue
        lines = [(top, c) for top, c in _lines(body, starts) if not _is_furniture(c)]

        anchors = [i for i, (_, c) in enumerate(lines) if _is_anchor(c)]
        extra: dict[int, list[tuple[float, str]]] = {i: [] for i in anchors}
        carried_over: list[str] = []
        for i, (top, c) in enumerate(lines):
            if i in extra or set(c) != {"reason"}:
                continue
            if not anchors or top < lines[anchors[0]][0] - CONT_GAP:
                carried_over.append(c["reason"])
                continue
            nearest = min(anchors, key=lambda a: abs(lines[a][0] - top))
            extra[nearest].append((top, c["reason"]))
        if carried_over and rows:
            rows[-1]["reason"] = " ".join([rows[-1]["reason"], *carried_over]).strip()

        for i, (top, c) in enumerate(lines):
            if i not in extra:
                if set(c) != {"reason"}:
                    carry.update({k: c[k] for k in CONTEXT if c.get(k)})
                continue
            carry.update({k: c[k] for k in CONTEXT if c.get(k)})
            parts = sorted(extra[i] + ([(top, c["reason"])] if c.get("reason") else []))
            reason = " ".join(t for _, t in parts).strip()
            text = " ".join(c.values()).upper()
            row = {**carry, "player": c.get("player", ""), "status": c.get("status", ""), "reason": reason}
            if NOT_SUBMITTED in text and not row["status"]:
                row.update(player="", status="Not Yet Submitted", reason="")
            rows.append(row)
    for r in rows:
        r["team_tricode"] = TEAM_TRICODE.get(r["team"], "")
        last, _, first = r["player"].partition(",")
        r["player_name"] = f"{first.strip()} {last.strip()}".strip() if first else r["player"]
    return rows


def parse(pdf_bytes: bytes) -> list[dict]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [p.extract_words(x_tolerance=1.5, y_tolerance=2) for p in pdf.pages]
    return parse_words(pages)

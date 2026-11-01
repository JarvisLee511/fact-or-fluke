"""Paths and time helpers. Every date in this project is an NBA (US Eastern) date, never the laptop's local time."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"

ET = ZoneInfo("America/New_York")


def now_et() -> datetime:
    return datetime.now(ET)


def today_et() -> date:
    return now_et().date()


def season_of(d: date) -> str:
    """NBA season label for a date, e.g. 2026-11-01 -> '2026-27'. Seasons roll over on Aug 1."""
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"

"""Paths and time helpers. Every date in this project is an NBA (US Eastern) date, never the laptop's local time.

Importing this module also loads the git-ignored ROOT/.env (API keys on the laptop) into os.environ,
without overriding variables that are already set (GitHub Actions passes its secrets that way).
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"

ET = ZoneInfo("America/New_York")


def load_env(path: Path = ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_env()


def now_et() -> datetime:
    return datetime.now(ET)


def today_et() -> date:
    return now_et().date()


def season_of(d: date) -> str:
    """NBA season label for a date, e.g. 2026-11-01 -> '2026-27'. Seasons roll over on Aug 1."""
    start = d.year if d.month >= 8 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"

"""Raw response archive: data/raw/<parts...>.json.gz, written with an atomic rename.

Per-game files are written once and never edited, so the database can always be rebuilt from them.
"Live" documents (schedule, season-to-date dashboards) are archived per ET date; a same-day refresh
overwrites that day's file.
"""
from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

from ..config import RAW


def path(*parts: str) -> Path:
    *dirs, name = parts
    return RAW.joinpath(*dirs, f"{name}.json.gz")


def exists(*parts: str) -> bool:
    return path(*parts).exists()


def save(obj, *parts: str) -> Path:
    p = path(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, p)
    return p


def load(*parts: str):
    with gzip.open(path(*parts), "rt", encoding="utf-8") as f:
        return json.load(f)


def files(*dirs: str) -> list[Path]:
    return sorted(RAW.joinpath(*dirs).glob("*.json.gz"))


def read(p: Path):
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)

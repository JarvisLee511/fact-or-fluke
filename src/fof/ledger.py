"""Append-only prediction and paper-bet ledgers (JSON lines in the private repo).

Lines are only ever appended, before tip-off; results are joined in later from the games table, never
written back. The private repo's git history doubles as proof that nothing was edited after the fact.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

LEDGER_DIR = ROOT / "private" / "ledger"
PREDICTIONS = LEDGER_DIR / "predictions.jsonl"
BETS = LEDGER_DIR / "bets.jsonl"


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(path: Path, rows: list[dict]) -> int:
    """Append rows whose id is not in the file yet. Returns how many were written."""
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = {r["id"] for r in read(path)}
    new = [r for r in rows if r["id"] not in seen]
    with path.open("a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    return len(new)

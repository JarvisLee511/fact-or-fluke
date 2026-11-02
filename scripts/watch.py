"""One look of the pre-game watch (fof.watch), run by the private repo's watch workflow every 15 minutes.

    python scripts/watch.py --repo <private repo checkout> [--dry] [--at 2026-11-02T18:30-05:00]

--dry makes no odds calls, sends nothing and writes nothing; --at pretends it is that time (testing).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from fof import watch


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--at", type=datetime.fromisoformat, default=None)
    args = ap.parse_args()
    print(json.dumps(watch.run(args.repo, args.at, args.dry), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

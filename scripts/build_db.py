"""Rebuild data/fof.duckdb from the raw archive."""
import sys
import time

from fof.store.build import build

t0 = time.time()
counts = build()
print(f"built in {time.time() - t0:.0f}s: {counts}")
sys.exit(0)

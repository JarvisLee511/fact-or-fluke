"""Rebuild data/fof.duckdb from the raw archive."""
import sys
import time

from fof.store.build import build

t0 = time.time()
print(f"built in {time.time() - t0:.0f}s: {build()}")
sys.exit(0)

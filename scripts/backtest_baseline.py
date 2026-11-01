"""Out-of-sample check of the baseline: fit on 2024-25, score every 2025-26 game it never saw."""
from __future__ import annotations

import sys

import numpy as np

from fof.model import baseline, elo
from fof.store import db

con = db.connect(read_only=True)
cols = ["game_id", "season", "game_date", "home_id", "away_id", "home_score", "away_score", "neutral", "status"]
games = [dict(zip(cols, r)) for r in con.execute(
    f"select {', '.join(cols)} from games where season in ('2024-25', '2025-26') order by tip_utc").fetchall()]
rows = [r for r in baseline.feature_rows(games) if r["status"] == 3]
train = [r for r in rows if r["season"] == "2024-25" and r["game_date"].month not in (10,)]
test = [r for r in rows if r["season"] == "2025-26"]
Xtr, ytr = np.array([r["x"] for r in train]), np.array([float(r["home_score"] > r["away_score"]) for r in train])
Xte, yte = np.array([r["x"] for r in test]), np.array([float(r["home_score"] > r["away_score"]) for r in test])

w = baseline.fit(Xtr, ytr)
p_model = baseline.predict(w, Xte)
p_home = np.full(len(yte), ytr.mean())
p_elo = np.array([elo.expected(r["elo_home"] + (0 if r["neutral"] else elo.HFA) - r["elo_away"]) for r in test])

print(f"train 2024-25 n={len(train)} (home win rate {ytr.mean():.3f}); test 2025-26 n={len(test)} "
      f"(home win rate {yte.mean():.3f})")
print("weights", dict(zip(["intercept"] + baseline.FEATURES, np.round(w, 4))))
for name, p in (("always home", p_home), ("Elo only (538 formula)", p_elo), ("baseline model", p_model)):
    m = baseline.metrics(p, yte)
    print(f"{name:<24} acc {m['accuracy']:.3f}  log loss {m['log_loss']:.4f}  brier {m['brier']:.4f}")
print("calibration (predicted, actual, n):")
for pr, ac, n in baseline.calibration(p_model, yte):
    print(f"  {pr:.2f} -> {ac:.2f}  ({n})")
sys.exit(0)

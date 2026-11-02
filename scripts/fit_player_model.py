"""Refit the v2 win model once a season, after scripts/backtest.py (daily refits) has rewritten
data/backtest/rows.pkl: the logistic weights on every completed season's backtest rows, and the play rates
behind the expected minutes. Writes src/fof/model/player_v2.json, which the daily run reads.

    python scripts/fit_player_model.py
"""
from __future__ import annotations

import json
import sys

import pandas as pd

import backtest as bt
from fof.config import DATA, season_of, today_et
from fof.model import baseline, minutes, player
from fof.store import db


def main() -> int:
    df = pd.read_pickle(DATA / "backtest" / "rows.pkl")
    train = df[(df.season < season_of(today_et())) & df[player.FEATURES].notna().all(axis=1)]
    w = baseline.fit(train[player.FEATURES].to_numpy(), train.y.to_numpy())
    con = db.connect(read_only=True)
    first = con.execute("select min(g.season) from stint_checks c join games g using (game_id) where c.ok").fetchone()[0]
    rates, _, report_rates = bt.calibration(con, minutes.team_games(con), first)
    con.close()
    out = {"model": player.MODEL, "fitted": today_et().isoformat(), "seasons": sorted(train.season.unique()),
           "games": len(train), "features": player.FEATURES, "weights": [round(float(v), 6) for v in w],
           "rates": {str(k): round(v, 6) for k, v in sorted(rates.items())},
           "report_rates": {"status": {k: round(v, 6) for k, v in sorted(report_rates["status"].items())},
                            "unlisted": {str(k): round(v, 6) for k, v in sorted(report_rates["unlisted"].items())}}}
    player.PARAMS.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: out[k] for k in ("seasons", "games", "features", "weights")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

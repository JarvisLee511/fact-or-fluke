# Fact or Fluke

**Live: <https://jarvislee511.github.io/fact-or-fluke/>** (English or 中文: the page follows your
browser's language, and the EN / 中文 switch remembers your choice)

A daily NBA analytics platform. Every morning, after last night's tracking data is published, it

1. **ranks fun facts by how much evidence backs them.** It scans every player and team for
   patterns (catch-and-shoot share, who assists whom, clutch takeovers, splits by quarter, half,
   side of the floor, home and away), compares a player's patterns with the 30 players most
   similar to him in role, and ranks what survives by the strength of the evidence. Patterns that look remarkable
   but that luck alone would produce somewhere among the players scanned get a **Fluke**
   verdict instead, with the odds spelled out.
2. **predicts every game and benchmarks it against the betting market:** player-impact ratings
   weighted by each player's expected minutes from the official injury report, scored against
   de-vigged sportsbook lines.

## Results

Walk-forward backtest, re-scored daily as the live system would have been. Every setting was
tuned on 2018-19 to 2020-21 only; the numbers below are the held-out seasons 2021-22 to
2025-26, on the 5,766 games that have a market line.

| Model | Log loss | Accuracy |
|---|---|---|
| Elo + home court + rest | 0.6248 | 65.1% |
| **Player model** (RAPM × injury-report minutes, + Elo) | **0.6150** | 66.9% |
| Betting market (de-vigged moneyline) | 0.6016 | 67.7% |

The player model closes 42% of the gap between Elo and the market. A gradient-boosted model
was tried in its place and scored worse than logistic regression, so it was dropped.
Simulated betting on the site's own rules does not beat the bookmakers' margin, so the
ledger stays on paper.

## How it works

| Step | What happens |
|---|---|
| Collect | Box scores, play-by-play and tracking dashboards from stats.nba.com; the official NBA injury report (PDF); odds from 5 Massachusetts sportsbooks via The Odds API. Raw responses are kept immutable (`data/raw/**.json.gz`) and DuckDB is rebuilt from them |
| Lineups | Who was on the floor for every possession, rebuilt from play-by-play substitutions: 12,915 of 12,956 games (99.7%) pass the checks (each player's minutes within 5 seconds of the box score, and the score consistent) |
| Player impact | Offensive and defensive RAPM, a ridge regression over 396K lineup stints (λ = 4000, seasons weighted ×0.7 going back three), with box-score priors fitted in the same equation |
| Expected minutes | From the latest official injury report (5,503 reports and 573,580 rows parsed since 2019) and today's roster |
| Win probability | Logistic regression on Elo, the minutes-weighted rating gap, home court and rest |
| Fun facts | Each pattern is shrunk toward its similar-role baseline (empirical Bayes, prior strength by method of moments), with Benjamini–Hochberg control across the scan. A split is a Fluke when the number of players scanned times its two-sided p-value is at least 1: luck alone would produce one |
| Publish | Static JSON for the site (GitHub Pages) and an email digest |

Scale: 11 seasons (2016-17 to 2026-27), 14,825 games, 6.0M play-by-play events.

## Automation

- A Windows scheduled task runs `scripts/daily.py` every 30 minutes from 6:00 to 12:30 ET and
  proceeds once last night's tracking data is out. Predictions are logged before tip-off to an
  append-only ledger in a separate private repo, so the record cannot be edited after the fact.
- stats.nba.com does not answer cloud runners, so the heavy work runs locally. A private
  GitHub Actions repo snapshots odds and watches pre-game injury reports, recomputing a game's
  probability from the morning's saved table when a report changes.

## Known limits

- GitHub's scheduler runs far fewer of the 15-minute evening checks than it is asked to, so
  pre-game updates can be missed; the morning prediction does not depend on them.
- Historical odds for the backtest come from a public dataset whose open/close timing is not
  documented. They are used for internal evaluation only and are not published.
- Not affiliated with the NBA. Analysis and entertainment, not betting advice; every bet on
  the site is simulated.

## Repository

```
src/fof/ingest/   fetchers, plus the parser for the injury-report PDFs
src/fof/store/    raw files -> DuckDB, lineup stints
src/fof/model/    Elo baseline, RAPM, expected minutes, the player model
src/fof/facts/    pattern families, evidence, standings, Fluke verdicts
src/fof/          daily run, scorecard, publishing, email
site/             the static site (no framework, no build step)
scripts/          daily entry point, backfills, backtest, model fitting
tests/            58 tests
```

## Run it

```bash
python -m venv .venv
.venv/Scripts/pip install -e .           # Windows; .venv/bin/pip elsewhere
python -m pytest                          # tests need no network and no data
python scripts/backfill.py                # one-time history pull (hours; resumable)
python scripts/build_db.py                # rebuild DuckDB from the raw files
python scripts/backtest.py                # the walk-forward table above
python scripts/daily.py                   # what the scheduled task runs
```

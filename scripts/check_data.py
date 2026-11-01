"""Per-season data quality report for the history the model learns from (prints a table, changes nothing).

games      finished regular-season / play-in / playoff games in the schedule
box, pbp   how many of them have a box score / play-by-play
minutes    team-games whose players' minutes add up to 240 (+25 per overtime), within 10 seconds
stints     games whose lineup stints pass every check (fof/store/stints.py)
odds       games with a historical moneyline, and the de-vigged market's log loss on them
"""
import sys

from fof.store import db

con = db.connect(read_only=True)
rows = con.execute("""
    with g as (select game_id, season from games
               where status = 3 and season_type in ('Regular Season', 'PlayIn', 'Playoffs')),
    periods as (select game_id, max(period) as n from pbp group by 1),
    team_min as (
        select pg.game_id, pg.team_id, sum(pg.seconds) as s from player_games pg group by 1, 2),
    minutes as (
        select t.game_id, bool_and(abs(t.s - 5 * (2880 + 300 * greatest(coalesce(p.n, 4) - 4, 0))) <= 10) as ok
        from team_min t left join periods p using (game_id) group by 1),
    market as (
        select o.game_id, gm.home_score > gm.away_score as home_won,
               (case when ml_home > 0 then 100 / (ml_home + 100) else -ml_home / (100 - ml_home) end) as ph,
               (case when ml_away > 0 then 100 / (ml_away + 100) else -ml_away / (100 - ml_away) end) as pa
        from odds_history o join games gm using (game_id))
    select g.season, count(*) as games,
           count(*) filter (where g.game_id in (select game_id from player_games)) as box,
           count(*) filter (where g.game_id in (select game_id from periods)) as pbp,
           count(*) filter (where m.ok) as minutes_ok,
           count(*) filter (where c.ok) as stints_ok,
           count(mk.game_id) as odds,
           avg(-ln(case when mk.home_won then mk.ph / (mk.ph + mk.pa) else mk.pa / (mk.ph + mk.pa) end)) as market_ll
    from g left join minutes m using (game_id) left join stint_checks c using (game_id)
    left join market mk using (game_id)
    group by 1 order by 1""").fetchall()
print(f"{'season':<9}{'games':>6}{'box':>6}{'pbp':>6}{'minutes':>9}{'stints':>8}{'odds':>6}{'mkt LL':>8}")
for s, n, box, pbp, mins, ok, odds, ll in rows:
    print(f"{s:<9}{n:>6}{box:>6}{pbp:>6}{mins:>9}{ok:>8}{odds:>6}{(f'{ll:.3f}' if ll else '-'):>8}")
sys.exit(0)

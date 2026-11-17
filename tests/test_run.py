import logging
import subprocess
from datetime import date, datetime

from fof import run
from fof.config import ET
from fof.ingest.http import FetchError


def _git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def test_a_rerun_with_nothing_staged_commits_nothing_and_warns_nothing(tmp_path, caplog):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.com")
    (tmp_path / "ledger.jsonl").write_text("{}\n")
    _git(tmp_path, "add", "ledger.jsonl")
    with caplog.at_level(logging.WARNING, logger="fof"):
        run._commit("ledger 2026-11-02", tmp_path)
        run._commit("ledger 2026-11-02", tmp_path)      # the same day again: nothing new
    assert _git(tmp_path, "log", "--format=%s").splitlines() == ["ledger 2026-11-02"]
    assert not caplog.records


def _commit_file(repo, name, message):
    (repo / name).write_text(message + "\n")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)


def _clones(tmp_path):
    """The private repo's remote, the laptop's clone (at private/, where the run looks) and a cloud workflow's."""
    seed, remote = tmp_path / "seed", tmp_path / "remote.git"
    seed.mkdir()
    _git(seed, "init", "-q")
    _git(seed, "config", "user.name", "test")
    _git(seed, "config", "user.email", "test@example.com")
    _commit_file(seed, "README", "start")
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(remote)], check=True, capture_output=True)
    clones = []
    for name in ("private", "cloud"):
        d = tmp_path / name
        subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True, capture_output=True)
        _git(d, "config", "user.name", "test")
        _git(d, "config", "user.email", "test@example.com")
        clones.append(d)
    return remote, *clones


def test_a_push_the_cloud_beat_is_pulled_again_and_retried(tmp_path, monkeypatch):
    remote, laptop, cloud = _clones(tmp_path)
    _commit_file(laptop, "ledger.jsonl", "ledger 2026-11-07")
    real, raced = run._git, []

    def racing(args, repo=None):            # the cloud pushes a snapshot between the laptop's pull and its push
        if args[0] == "push" and not raced:
            raced.append(True)
            _commit_file(cloud, "snapshot.json", "odds snapshot")
            _git(cloud, "push", "-q")
        return real(args, repo)

    monkeypatch.setattr(run, "_git", racing)
    monkeypatch.setattr(run, "sleep", lambda s: None)
    assert run._push(laptop)
    assert _git(remote, "log", "--format=%s").splitlines() == ["ledger 2026-11-07", "odds snapshot", "start"]


def test_a_day_already_done_makes_the_push_its_run_could_not(tmp_path, monkeypatch):
    remote, laptop, _ = _clones(tmp_path)
    _commit_file(laptop, "ledger.jsonl", "ledger 2026-11-07")        # committed, every push refused
    for name, path in (("ROOT", tmp_path), ("DATA", tmp_path / "data"), ("STATE", tmp_path / "state")):
        monkeypatch.setattr(run, name, path)
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))      # main() adds a stdout handler
    run._save_state(date(2026, 11, 7), {"emailed": True})
    assert not run._unpushed(tmp_path / "cloud") and run._unpushed()
    assert run.main(["--day", "2026-11-07"]) == 0
    assert _git(remote, "log", "-1", "--format=%s").strip() == "ledger 2026-11-07" and not run._unpushed()


def test_an_odds_api_that_is_down_is_waited_for_until_the_noon_cutoff(tmp_path, monkeypatch):
    now = [datetime(2026, 11, 7, 9, 30, tzinfo=ET)]
    slow = []

    def down(*args, **kwargs):
        raise FetchError("https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey=secret", 503)

    monkeypatch.setattr(run, "ROOT", tmp_path)                                 # no private repo: no git
    monkeypatch.setattr(run, "now_et", lambda: now[0])
    monkeypatch.setenv("ODDS_API_KEY", "secret")
    monkeypatch.setattr(run.odds, "snapshot", down)
    monkeypatch.setattr(run.collect, "schedule", lambda season, day, **kw: {"leagueSchedule": {"gameDates": []}})
    monkeypatch.setattr(run.collect, "dashboards", lambda *args, **kwargs: slow.append("dashboards"))
    monkeypatch.setattr(run.collect, "player_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(run.injury, "latest_stamps", lambda season: [])
    info = run.collect_day(date(2026, 11, 7), force=False)
    assert info["go"] is False and info["odds"] is False and not slow          # stopped before the slow fetches
    now[0] = datetime(2026, 11, 7, 12, 0, tzinfo=ET)
    info = run.collect_day(date(2026, 11, 7), force=False)
    assert info["go"] is True and info["odds"] is False and slow == ["dashboards"]


def test_a_stats_nba_that_does_not_answer_sends_the_morning_to_espn(tmp_path, monkeypatch):
    """11/11-11/16: stats.nba.com left every request hanging; each morning failed at its first fetch."""
    now = [datetime(2026, 11, 17, 6, 0, tzinfo=ET)]

    def hangs(*args, **kwargs):
        raise FetchError("https://stats.nba.com/stats/scheduleleaguev2", None, b"The read operation timed out")

    def game(gid, day, status, espn_id):
        return {"gameId": gid, "gameDateEst": f"{day}T00:00:00Z", "gameStatus": status, "espnId": espn_id,
                "postponedStatus": "N", "homeTeam": {"teamTricode": "BOS", "teamId": 1610612738},
                "awayTeam": {"teamTricode": "MIA", "teamId": 1610612748}}

    converted = []

    def convert(g, season, ids):
        converted.append(g["gameId"])
        run.raw.save({}, "games", season, "box", g["gameId"])

    monkeypatch.setattr(run, "ROOT", tmp_path)                                 # no private repo: no git
    monkeypatch.setattr(run, "now_et", lambda: now[0])
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.setattr(run.raw, "RAW", tmp_path / "raw")
    monkeypatch.setattr(run.collect, "schedule", hangs)
    run.raw.save({"leagueSchedule": {"gameDates": [{"games": [
        game("0022600239", "2026-11-15", 3, "11"), game("0022600240", "2026-11-16", 3, "12"),
        game("0022600241", "2026-11-17", 1, "13")]}]}}, "schedule", "2026-27", "2026-11-10")
    monkeypatch.setattr(run.espn, "schedule", lambda base, base_day, day: {**base, "source": "espn"})
    monkeypatch.setattr(run.espn, "game", convert)
    monkeypatch.setattr(run.espn, "player_index", lambda: [])
    monkeypatch.setattr(run.espn, "rosters", lambda ids, teams: {"source": "espn", "teams": sorted(teams)})
    monkeypatch.setattr(run.injury, "latest_stamps", lambda season: [])
    info = run.collect_day(date(2026, 11, 17), force=False)
    assert info["source"] == "espn" and info["complete"] and info["go"] is False      # ready, but before 08:30
    assert converted == ["0022600239", "0022600240"]               # every finished game the archive lacked
    assert run.raw.load("schedule", "2026-27", "2026-11-17")["source"] == "espn"
    assert not run.raw.exists("players", "2026-27", "2026-11-17")
    now[0] = datetime(2026, 11, 17, 8, 30, tzinfo=ET)
    info = run.collect_day(date(2026, 11, 17), force=False)
    assert info["go"] is True and info["finals"] == info["scheduled"] == 1
    assert converted == ["0022600239", "0022600240"]               # nothing converted twice
    assert run.raw.load("players", "2026-27", "2026-11-17")["teams"] == ["BOS", "MIA"]   # today's rosters


def _union_attrs(repo):
    (repo / ".gitattributes").write_text("ledger/*.jsonl merge=union\n")
    (repo / "ledger").mkdir(exist_ok=True)
    (repo / "ledger" / "pregame.jsonl").write_text("")
    _git(repo, "add", ".gitattributes", "ledger/pregame.jsonl")
    _git(repo, "commit", "-q", "-m", "attrs")
    _git(repo, "push", "-q")


def _append(repo, line, message):
    with open(repo / "ledger" / "pregame.jsonl", "a") as f:
        f.write(line + "\n")
    _git(repo, "add", "ledger/pregame.jsonl")
    _git(repo, "commit", "-q", "-m", message)


def test_two_writers_appending_to_one_ledger_keep_both_lines(tmp_path, monkeypatch):
    """11/07: the cloud and another writer each added rows to ledger/pregame.jsonl; the rebase stopped on it."""
    remote, laptop, cloud = _clones(tmp_path)
    _union_attrs(cloud)
    _git(laptop, "pull", "-q")
    _append(cloud, '{"id": "cloud"}', "watch")
    _git(cloud, "push", "-q")
    _append(laptop, '{"id": "laptop"}', "ledger")
    monkeypatch.setattr(run, "sleep", lambda s: None)
    assert run._push(laptop)
    _git(cloud, "pull", "-q")
    assert (cloud / "ledger" / "pregame.jsonl").read_text().splitlines() == ['{"id": "cloud"}', '{"id": "laptop"}']


def test_a_pull_that_stops_on_a_conflict_never_leaves_the_repo_mid_rebase(tmp_path, monkeypatch):
    remote, laptop, cloud = _clones(tmp_path)
    _commit_file(cloud, "README", "cloud edit")
    _git(cloud, "push", "-q")
    _commit_file(laptop, "README", "laptop edit")                  # same file, both sides: a real conflict
    monkeypatch.setattr(run, "sleep", lambda s: None)
    assert not run._push(laptop)
    assert not (laptop / ".git" / "rebase-merge").exists() and not (laptop / ".git" / "rebase-apply").exists()
    assert _git(laptop, "status", "--porcelain") == ""
    assert _git(laptop, "log", "-1", "--format=%s").strip() == "laptop edit"   # the commit is kept for next time

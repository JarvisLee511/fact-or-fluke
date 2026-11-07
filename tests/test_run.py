import logging
import subprocess
from datetime import date

from fof import run


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

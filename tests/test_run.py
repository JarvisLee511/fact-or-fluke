import logging
import subprocess

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

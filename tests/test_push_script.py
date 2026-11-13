"""private/.github/push.sh, the cloud workflows' push (watch, record-odds)."""
import shutil
import subprocess
from pathlib import Path

import pytest

from test_run import _append, _clones, _commit_file, _git, _union_attrs

SCRIPT = Path(__file__).resolve().parents[1] / "private" / ".github" / "push.sh"
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(not SCRIPT.exists() or not BASH, reason="needs the private repo and bash")


def _push_sh(repo) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, str(SCRIPT)], cwd=repo, capture_output=True, text=True, timeout=120)


def test_the_cloud_push_keeps_both_ledgers_and_its_own_newer_state(tmp_path):
    """The 11/07 failure: a run started from an old commit, appended to the ledger and rewrote the day's state."""
    remote, other, cloud = _clones(tmp_path)
    _union_attrs(other)
    _commit_file(other, "state.json", "state 1")
    _git(other, "push", "-q")
    _git(cloud, "pull", "-q")
    _append(other, '{"id": "first run"}', "watch 1")
    _commit_file(other, "state.json", "state 2")
    _git(other, "push", "-q")
    _append(cloud, '{"id": "second run"}', "watch 2")                 # cloud never saw "watch 1"
    _commit_file(cloud, "state.json", "state 3")
    r = _push_sh(cloud)
    assert r.returncode == 0, r.stdout + r.stderr
    _git(other, "pull", "-q")
    assert (other / "ledger" / "pregame.jsonl").read_text().splitlines() == ['{"id": "first run"}',
                                                                              '{"id": "second run"}']
    assert (other / "state.json").read_text() == "state 3\n"


def test_a_push_that_cannot_land_fails_loudly_and_cleanly(tmp_path):
    remote, other, cloud = _clones(tmp_path)
    _commit_file(cloud, "README", "cloud edit")
    _git(cloud, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    r = subprocess.run([BASH, "-c", f"sleep() {{ :; }}; export -f sleep; '{BASH}' '{SCRIPT.as_posix()}'"],
                       cwd=cloud, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1 and "could not push after 5 tries" in r.stdout
    assert not (cloud / ".git" / "rebase-merge").exists()

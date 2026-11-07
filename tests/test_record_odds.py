import importlib.util
import sys
from pathlib import Path

from fof.ingest.http import FetchError


def test_an_odds_api_outage_records_nothing_and_does_not_fail_the_job(tmp_path, monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("record_odds", Path(__file__).parents[1] / "scripts" / "record_odds.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def down(*args, **kwargs):
        raise FetchError("https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey=secret", 503)

    monkeypatch.setattr(mod.odds, "snapshot", down)
    monkeypatch.setenv("ODDS_API_KEY", "secret")
    monkeypatch.setattr(sys, "argv", ["record_odds.py", "--out", str(tmp_path / "snapshots")])
    assert mod.main() == 0
    assert not (tmp_path / "snapshots").exists()
    out = capsys.readouterr().out
    assert "nothing recorded" in out and "secret" not in out

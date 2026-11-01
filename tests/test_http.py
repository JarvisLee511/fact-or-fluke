from fof.ingest.http import FetchError, redact


def test_redact_hides_keys_in_query_strings():
    url = "https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey=abc123&regions=us"
    assert redact(url) == "https://api.the-odds-api.com/v4/sports/basketball_nba/odds?apiKey=***&regions=us"
    assert "abc123" not in str(FetchError(url, 401, b"denied"))
    assert redact("https://x.test/a?api_key=1&token=2&q=3") == "https://x.test/a?api_key=***&token=***&q=3"

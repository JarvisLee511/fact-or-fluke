from datetime import date

from fof import digest

DAY = date(2026, 11, 3)
SITE = "https://jarvislee511.github.io/fact-or-fluke/"
CHI = dict(home="CHI", away="ATL", p_home=0.5057, tip_utc="2026-11-04T00:30:00+00:00", market_p_home=0.46,
           best={"CHI": [2.10, "DraftKings"], "ATL": [1.80, "FanDuel"]}, ev={"CHI": 0.062, "ATL": -0.1103},
           pick="CHI", suspect=None, why={"home": 0.03, "absent": 0.02, "players": -0.04, "elo": 0.004})
LAL = dict(home="LAL", away="DEN", p_home=0.45, tip_utc="2026-11-04T03:00:00+00:00", market_p_home=0.47,
           best={"LAL": [2.05, "BetMGM"], "DEN": [1.83, "FanDuel"]}, ev={"LAL": -0.0775, "DEN": 0.0065},
           pick=None, suspect=None, why={"players": -0.05})


def test_only_the_picks_go_out_with_the_lowest_price_still_worth_it_and_why():
    subject, text, html_doc = digest.compose(DAY, [CHI, LAL], SITE)
    assert subject == "Fact or Fluke｜11/3（二） 今天 1 注"
    assert "19:30  ATL @ CHI" in text and "投 CHI：2.10 @DraftKings，期望值 +6.2%" in text
    assert "賠率低於 2.04 就不值得投" in text                       # 1.03 / 0.5057 = 2.037
    assert "原因：模型 CHI 51%、賭盤 46%；CHI 主場、ATL 傷兵影響較大" in text   # only what favours CHI, 1 point or more
    assert "DEN" not in text and "LAL" not in text                     # the game not worth a bet is left out
    assert "<b>19:30  ATL @ CHI</b>" in html_doc and SITE in text


def test_an_away_pick_is_described_from_its_own_side():
    row = dict(LAL, best={"LAL": [2.05, "BetMGM"], "DEN": [1.96, "Caesars"]}, ev={"LAL": -0.0775, "DEN": 0.078},
               pick="DEN")
    _, text, _ = digest.compose(DAY, [row], None)
    assert "22:00  DEN @ LAL" in text and "投 DEN：1.96 @Caesars，期望值 +7.8%" in text
    assert "賠率低於 1.87 就不值得投" in text and "原因：模型 DEN 55%、賭盤 53%；DEN 陣容實力較強" in text


def test_the_lowest_price_is_never_above_the_one_on_offer():
    assert digest.min_price(0.5057, 2.10) == 2.04
    assert digest.min_price(0.5612, 1.8333) == 1.8333          # 1.03 / 0.5612 rounds to 1.84


def test_a_day_without_a_pick_says_so_in_one_line():
    subject, text, _ = digest.compose(DAY, [LAL], SITE)
    assert subject.endswith("今天沒有值得投注的比賽") and "今天沒有值得投注的比賽" in text and "LAL" not in text
    assert digest.compose(DAY, [], None)[0].endswith("今天沒有比賽")
    unpriced = dict(LAL, best=None, ev=None)
    subject, text, _ = digest.compose(DAY, [unpriced], None)
    assert subject.endswith("今天抓不到賠率") and "沒辦法判斷哪幾場值得投" in text
    _, text, _ = digest.compose(DAY, [CHI, unpriced], None)
    assert "今天 1 注" in text and "另有 1 場還沒有賠率" in text

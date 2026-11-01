"""Injury report parsing on synthetic word boxes laid out like the real PDF (no NBA files in the repo)."""
from fof.ingest.injury import parse_words, stamp_of, stamp_time

HEADER = [("Game", 23.1), ("Date", 53.0), ("Game", 119.6), ("Time", 149.4), ("Matchup", 200.0), ("Team", 264.2),
          ("Player", 425.0), ("Name", 456.9), ("Current", 585.7), ("Status", 624.1), ("Reason", 666.1)]


def words(*items):
    """items: (text, x0, top)"""
    return [{"text": t, "x0": x, "top": y} for t, x, y in items]


TITLE = [("Injury", 288.1, 45.5), ("Report:", 354.6, 45.5), ("11/01/26", 437.3, 45.5), ("12:45", 538.8, 45.5),
         ("AM", 601.5, 45.5)]


def page(*body):
    """Page 1: title, header row, body."""
    return words(*TITLE, *[(t, x, 107.7) for t, x in HEADER], *body)


def later_page(*body):
    """Pages 2+: title and body only (no header row)."""
    return words(*TITLE, *body)


def test_forward_fill_and_centred_two_line_reason():
    p = page(
        ("11/01/2026", 24.1, 128.9), ("03:30", 120.6, 128.9), ("(ET)", 145.8, 128.9), ("BOS@ORL", 201.0, 128.9),
        ("Boston", 265.2, 128.9), ("Celtics", 296.0, 128.9), ("Carter,", 426.0, 128.9), ("Devin", 456.2, 128.9),
        ("Out", 586.7, 128.9), ("Injury/Illness", 667.1, 128.9), ("-", 721.8, 128.9), ("Illness", 727.1, 128.9),
        ("Robinson,", 426.0, 151.0), ("Mitchell", 468.7, 151.0), ("Questionable", 586.7, 151.0), ("Rest", 667.1, 151.0),
        ("Injury/Illness", 667.1, 174.0), ("-", 721.8, 174.0), ("Right", 727.1, 174.0), ("Ankle", 750.4, 174.0),
        ("Orlando", 265.2, 181.0), ("Magic", 300.5, 181.0), ("Banchero,", 426.0, 181.0), ("Paolo", 469.4, 181.0),
        ("Out", 586.7, 181.0), ("Sprain", 667.1, 188.1),
        ("Page", 380.0, 560.0), ("1", 405.0, 560.0), ("of", 412.0, 560.0), ("5", 425.0, 560.0),
    )
    rows = parse_words([p])
    assert [r["player_name"] for r in rows] == ["Devin Carter", "Mitchell Robinson", "Paolo Banchero"]
    carter, robinson, banchero = rows
    assert carter["team_tricode"] == "BOS" and carter["matchup"] == "BOS@ORL" and carter["game_time"] == "03:30 (ET)"
    assert robinson["team_tricode"] == "BOS" and robinson["status"] == "Questionable" and robinson["reason"] == "Rest"
    assert banchero["team_tricode"] == "ORL" and banchero["game_date"] == "11/01/2026"
    assert banchero["reason"] == "Injury/Illness - Right Ankle Sprain"


def test_headerless_pages_reason_split_by_page_break_and_not_submitted():
    p1 = page(("11/01/2026", 24.1, 128.9), ("05:00", 120.6, 128.9), ("(ET)", 145.8, 128.9), ("BKN@IND", 201.0, 128.9),
              ("Brooklyn", 265.2, 128.9), ("Nets", 300.0, 128.9), ("NOT", 667.1, 128.9), ("YET", 687.3, 128.9),
              ("SUBMITTED", 704.2, 128.9),
              ("Indiana", 265.2, 502.7), ("Pacers", 297.7, 502.7), ("Furphy,", 426.0, 502.7), ("Johnny", 459.1, 502.7),
              ("Out", 586.7, 502.7), ("Injury/Illness", 667.1, 502.7), ("-", 721.8, 502.7), ("Right", 727.1, 502.7),
              ("ACL", 750.4, 502.7), ("Repair", 768.0, 502.7), ("/", 796.5, 502.7),
              ("Page", 398.5, 538.1), ("1", 420.4, 538.1), ("of", 427.8, 538.1), ("2", 438.3, 538.1))
    p2 = later_page(("Surgery", 667.1, 81.6),
                    ("Haliburton,", 426.0, 103.6), ("Tyrese", 474.2, 103.6), ("Out", 586.7, 103.6),
                    ("Injury/Illness", 667.1, 103.6), ("-", 721.8, 103.6), ("Left", 727.1, 103.6),
                    ("Hamstring", 745.0, 103.6), ("Strain", 789.2, 103.6),
                    ("Page", 398.5, 538.1), ("2", 420.4, 538.1), ("of", 427.8, 538.1), ("2", 438.3, 538.1))
    nets, furphy, haliburton = parse_words([p1, p2])
    assert nets["status"] == "Not Yet Submitted" and nets["team_tricode"] == "BKN" and nets["player"] == ""
    assert furphy["reason"] == "Injury/Illness - Right ACL Repair / Surgery"
    assert haliburton["team_tricode"] == "IND" and haliburton["matchup"] == "BKN@IND"
    assert haliburton["game_time"] == "05:00 (ET)" and haliburton["reason"] == "Injury/Illness - Left Hamstring Strain"


def test_stamp_round_trip():
    assert stamp_of(stamp_time("2026-11-01_12_45AM")) == "2026-11-01_12_45AM"
    assert stamp_time("2026-11-01_05_00PM").hour == 17

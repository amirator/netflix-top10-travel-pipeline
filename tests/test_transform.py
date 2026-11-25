import pandas as pd

from top10 import transform


def test_travel_threshold_is_half_of_countries_rounded_up():
    assert transform.travel_threshold(93) == 47
    assert transform.travel_threshold(94) == 47


def test_language_match_prefers_netflix_linked_and_rejects_ambiguity():
    titles = pd.DataFrame({
        "kind": ["TV", "TV", "Film"], "show_title": ["Kingdom", "Two Shows", "Old Film"],
        "debut_year": [2021, 2022, 2023], "in_cohort": [True, True, True],
    })
    wd = pd.DataFrame([
        # Netflix-linked Korean series wins over a non-Netflix Japanese one
        ("Kingdom", "Q1", "Korean", "2019", True, True),
        ("Kingdom", "Q2", "Japanese", "2012", False, True),
        # two Netflix-linked series with the same label -> ambiguous
        ("Two Shows", "Q3", "Spanish", "2017", True, True),
        ("Two Shows", "Q4", "Korean", "2022", True, True),
        # film published 30 years before its Netflix debut -> rejected
        ("Old Film", "Q5", "French", "1993", False, False),
    ], columns=["label", "qid", "language", "year", "netflix_linked", "has_seasons_or_episodes"])
    out = transform.match_languages(titles, wd).set_index("show_title")
    assert out.loc["Kingdom", "language"] == "Korean"
    assert out.loc["Two Shows", "language_match"] == "ambiguous"
    assert out.loc["Old Film", "language_match"] == "no candidate"

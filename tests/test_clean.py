import json

import pandas as pd
import pytest

from top10 import audit, clean, config


def test_na_handling_keeps_namibia_and_nulls_literal_na(tmp_path, monkeypatch):
    tsv = tmp_path / "all-weeks-countries.tsv"
    tsv.write_text("country_name\tcountry_iso2\tweek\tcategory\tweekly_rank\tshow_title\tseason_title\tcumulative_weeks_in_top_10\n"
                   "Namibia\tNA\t2024-01-07\tFilms\t1\tSome Film\tN/A\t1\n", encoding="utf-8")
    monkeypatch.setattr(config, "RAW", tmp_path)
    df = clean.read_raw("countries")
    assert df.loc[0, "country_iso2"] == "NA"
    assert pd.isna(df.loc[0, "season_title"])


def test_quality_log_has_no_failures_and_counts_rows():
    if not config.QUALITY_LOG.exists():
        pytest.skip("run the pipeline first")
    log = json.loads(config.QUALITY_LOG.read_text())
    assert log["checks"], "no checks recorded"
    assert not [c for c in log["checks"] if c["status"] == "fail"]
    stages = {s["stage"] for s in log["stages"]}
    assert {"clean", "transform", "analyze", "load"} <= stages
    for s in log["stages"]:
        assert s["rows_out"] <= s["rows_in"] or s["stage"] == "load"


def test_window_cut_holds_back_newer_weeks(raw_paths, monkeypatch):
    audit.reset()
    raw = clean.read_raw("global")
    monkeypatch.setattr(config, "AS_OF_WEEK", "2025-12-28")
    df = clean.clean_global(raw)
    assert df["week"].max() == pd.Timestamp("2025-12-28")
    cut = [s for s in audit.STAGES if "freeze" in s["step"]][0]
    assert cut["rows_in"] - cut["rows_out"] == (pd.to_datetime(raw["week"]) > "2025-12-28").sum()
    audit.reset()

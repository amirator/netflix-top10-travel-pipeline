"""Reconcile the headline numbers to the RAW Netflix files with an independent pandas
implementation (no DuckDB, no pipeline code beyond config constants)."""
import math

import pandas as pd
import pytest

from top10 import config


@pytest.fixture(scope="module")
def recomputed(raw_paths):
    gp, cp = raw_paths
    g = pd.read_csv(gp, sep="\t", dtype=str, keep_default_na=False, na_values=["N/A"])
    c = pd.read_csv(cp, sep="\t", dtype=str, keep_default_na=False, na_values=["N/A"])
    g, c = (d[pd.to_datetime(d["week"]) <= config.AS_OF_WEEK].assign(
        week=lambda x: pd.to_datetime(x["week"]), season_title=lambda x: x["season_title"].fillna("<none>"))
        for d in (g, c))
    g["kind"] = g["category"].str[:2].map({"Fi": "Film", "TV": "TV"})
    g["ne"] = g["category"].str.contains("Non-English")
    c["kind"] = c["category"].map({"Films": "Film", "TV": "TV"})
    key = ["kind", "show_title", "season_title"]

    both = g.groupby(key)["ne"].nunique()
    collide = set(both[both > 1].index)
    ne = g[g["ne"]].copy()
    ne["hours"] = ne["weekly_hours_viewed"].astype(int)
    ne = ne.sort_values("week")
    first = ne.groupby(key).first()
    t = pd.DataFrame({
        "first_week": first["week"],
        "cum_first": first["cumulative_weeks_in_top_10"].astype(int),
        "global_weeks": ne.groupby(key).size(),
    })
    t["collide"] = [k in collide for k in t.index]
    cc = c.set_index(key)
    cc = cc[cc.index.isin(t.index[~t["collide"]])].reset_index()
    t["countries"] = cc.groupby(key)["country_iso2"].nunique().reindex(t.index).fillna(0)
    t["country_weeks"] = cc.groupby(key).size().reindex(t.index).fillna(0)
    debut = cc.merge(t["first_week"].reset_index(), on=key)
    debut = debut[debut["week"] == debut["first_week"]]
    t["debut_countries"] = debut.groupby(key)["country_iso2"].nunique().reindex(t.index).fillna(0)
    n_week = int(c.groupby("week")["country_iso2"].nunique().median())
    follow = (pd.Timestamp(config.AS_OF_WEEK) - t["first_week"]).dt.days // 7
    t["cohort"] = (t["cum_first"] == 1) & (t["first_week"] > config.FIRST_WEEK) & (follow >= config.FOLLOW_UP_WEEKS) & ~t["collide"]
    thr = math.ceil(config.MIN_COUNTRY_SHARE * n_week)
    t["travels"] = (t["countries"] >= thr) & (t["global_weeks"] >= config.MIN_GLOBAL_WEEKS)
    t.attrs["country_rows"] = len(cc)
    return t, n_week, thr


def test_raw_row_counts_in_study_window(raw_paths):
    gp, cp = raw_paths
    g = pd.read_csv(gp, sep="\t", usecols=["week"])
    c = pd.read_csv(cp, sep="\t", usecols=["week"])
    # 282 weeks x 4 lists x 10 rows; 52,522 country lists x 10 rows (as of 2026-11-22)
    assert (g["week"] <= config.AS_OF_WEEK).sum() == 11_280
    assert (c["week"] <= config.AS_OF_WEEK).sum() == 525_220


def test_headline_reconciles(recomputed, kpis):
    t, n_week, thr = recomputed
    co = t[t["cohort"]]
    assert n_week == kpis["countries_per_week"]
    assert thr == kpis["travel_min_countries"]
    assert len(t) == kpis["non_english_titles_all"]
    assert len(co) == kpis["cohort_titles"]
    assert int(co["travels"].sum()) == kpis["travellers"]
    assert round(co["travels"].mean(), 3) == kpis["travel_rate"]
    by_kind = co.groupby(level="kind")["travels"].mean().round(3)
    assert by_kind["TV"] == kpis["travel_rate_tv"]
    assert by_kind["Film"] == kpis["travel_rate_film"]


def test_debut_breadth_signal_reconciles(recomputed, kpis):
    t, _, _ = recomputed
    co = t[t["cohort"]]
    hi = co[co["debut_countries"] >= 40]
    lo = co[co["debut_countries"] < 10]
    assert len(hi) == kpis["debut_40plus_titles"]
    assert round(hi["travels"].mean(), 3) == kpis["debut_40plus_travel_rate"]
    assert len(lo) == kpis["debut_under10_titles"]
    assert round(lo["travels"].mean(), 3) == kpis["debut_under10_travel_rate"]


def test_top_traveller_reconciles(recomputed, kpis):
    t, _, _ = recomputed
    co = t[t["cohort"] & t["travels"]].sort_values("country_weeks", ascending=False)
    (kind, show, season), row = next(iter(co.iterrows()))
    assert (season if season != "<none>" else show) == kpis["top_traveller"]["title"]
    assert int(row["countries"]) == kpis["top_traveller"]["countries_reached"]
    assert int(row["country_weeks"]) == kpis["top_traveller"]["country_weeks"]
    assert int(row["global_weeks"]) == kpis["top_traveller"]["global_weeks"]


def test_country_weeks_total_reconciles(recomputed, kpis):
    t, _, _ = recomputed
    assert t.attrs["country_rows"] == kpis["title_country_weeks_total"]
    assert int(t["country_weeks"].sum()) == kpis["title_country_weeks_total"]

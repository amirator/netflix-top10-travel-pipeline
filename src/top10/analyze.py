"""Stage 4 - ANALYZE.

Answers the business question on the cohort of non-English titles whose debut we observe:
which titles travel, and what do they have in common (film vs TV, language, debut breadth,
weeks to peak, countries reached)? Produces small marts for the dashboard and kpis.json, the single
source of every number quoted in the README (tests fail if they drift).
"""
from __future__ import annotations

import json
import logging

import pandas as pd

from . import audit, config

log = logging.getLogger("analyze")
S = "analyze"
MIN_LANG_TITLES = 20  # languages with fewer matched cohort titles are grouped as "Other"


def _rate(df: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    g = df.groupby(by, observed=True)
    out = g.agg(titles=("travels", "size"), travellers=("travels", "sum"),
                median_countries=("countries_reached", "median"), median_global_weeks=("global_weeks", "median"),
                median_debut_countries=("debut_countries", "median")).reset_index()
    out["travel_rate"] = out["travellers"] / out["titles"]
    return out


def normalise_language(lang: str) -> str:
    return {"Brazilian Portuguese": "Portuguese", "European Portuguese": "Portuguese",
            "Mexican Spanish": "Spanish", "Latin American Spanish": "Spanish"}.get(lang, lang)


def run(t: dict[str, pd.DataFrame]) -> dict:
    titles = t["titles"].copy()
    params = t["params"].iloc[0].to_dict()
    titles["language_group"] = titles["language"].map(normalise_language)
    cohort = titles[titles["in_cohort"]].copy()
    trav = cohort[cohort["travels"]]
    rest = cohort[~cohort["travels"]]
    audit.stage(S, "titles -> cohort analysed", len(titles), len(cohort))

    by_kind = _rate(cohort, "kind")
    bands = ["0-9", "10-19", "20-39", "40+"]
    cohort["debut_countries_band"] = pd.Categorical(cohort["debut_countries_band"], bands, ordered=True)
    by_debut = _rate(cohort, "debut_countries_band")
    by_year = _rate(cohort, "debut_year")

    matched = cohort[cohort["language_match"] == "matched"].copy()
    counts = matched["language_group"].value_counts()
    small = counts[counts < MIN_LANG_TITLES].index
    matched.loc[matched["language_group"].isin(small), "language_group"] = "Other (smaller languages)"
    by_lang = _rate(matched, "language_group").sort_values(["travel_rate", "titles"], ascending=[False, False])
    unmatched_rate = float(cohort.loc[cohort["language_match"] != "matched", "travels"].mean())

    peak_dist = (cohort.assign(peak_bucket=cohort["weeks_to_peak"].clip(upper=4).map(
        {0: "debut week", 1: "week 2", 2: "week 3", 3: "week 4", 4: "week 5+"}))
        .groupby(["travels", "peak_bucket"]).size().rename("titles").reset_index())

    top = (trav.sort_values(["country_weeks", "countries_reached", "title"], ascending=[False, False, True])
           [["title", "kind", "language_group", "first_week", "global_weeks", "countries_reached",
             "country_weeks", "debut_countries", "weeks_to_peak", "best_rank"]].head(25).reset_index(drop=True))

    def r(x, n=3):
        return round(float(x), n)

    band = by_debut.set_index("debut_countries_band")
    kind = by_kind.set_index("kind")
    late = trav[trav["debut_countries"] < 20]
    top_lang = by_lang[by_lang["language_group"] != "Other (smaller languages)"]
    kpis = {
        "as_of_week": params["as_of_week"],
        "first_week": config.FIRST_WEEK,
        "weeks_in_study": int(pd.to_datetime(t["title_week"]["week"]).nunique()),
        "countries_per_week": int(params["countries_per_week"]),
        "travel_min_countries": int(params["travel_min_countries"]),
        "travel_min_global_weeks": int(params["travel_min_global_weeks"]),
        "non_english_titles_all": int(len(titles)),
        "cohort_titles": int(len(cohort)),
        "cohort_films": int(kind.loc["Film", "titles"]),
        "cohort_tv": int(kind.loc["TV", "titles"]),
        "travellers": int(len(trav)),
        "travel_rate": r(len(trav) / len(cohort)),
        "travel_rate_tv": r(kind.loc["TV", "travel_rate"]),
        "travel_rate_film": r(kind.loc["Film", "travel_rate"]),
        "travellers_tv": int(kind.loc["TV", "travellers"]),
        "travellers_film": int(kind.loc["Film", "travellers"]),
        "debut_40plus_titles": int(band.loc["40+", "titles"]),
        "debut_40plus_travel_rate": r(band.loc["40+", "travel_rate"]),
        "debut_under10_titles": int(band.loc["0-9", "titles"]),
        "debut_under10_travel_rate": r(band.loc["0-9", "travel_rate"]),
        "debut_20_39_travel_rate": r(band.loc["20-39", "travel_rate"]),
        "debut_10_19_travel_rate": r(band.loc["10-19", "travel_rate"]),
        "travellers_from_40plus_debut_share": r((trav["debut_countries"] >= 40).mean()),
        "late_bloomers": int(len(late)),
        "median_debut_countries_travellers": r(trav["debut_countries"].median(), 1),
        "median_debut_countries_others": r(rest["debut_countries"].median(), 1),
        "median_countries_travellers": r(trav["countries_reached"].median(), 1),
        "median_countries_others": r(rest["countries_reached"].median(), 1),
        "median_global_weeks_travellers": r(trav["global_weeks"].median(), 1),
        "median_global_weeks_others": r(rest["global_weeks"].median(), 1),
        "travellers_peak_by_week2_share": r((trav["weeks_to_peak"] <= 1).mean()),
        "others_peak_by_week2_share": r((rest["weeks_to_peak"] <= 1).mean()),
        "median_weeks_to_peak_travellers": r(trav["weeks_to_peak"].median(), 1),
        "language_matched_share": r((cohort["language_match"] == "matched").mean()),
        "language_matched_titles": int(len(matched)),
        "unmatched_travel_rate": r(unmatched_rate),
        "top_language_by_travellers": str(top_lang.sort_values("travellers", ascending=False).iloc[0]["language_group"]),
        "top_language_by_travellers_n": int(top_lang["travellers"].max()),
        "language_rates": {row.language_group: {"titles": int(row.titles), "travellers": int(row.travellers),
                                               "travel_rate": r(row.travel_rate)}
                           for row in by_lang.itertuples()},
        "top_traveller": {"title": top.iloc[0]["title"], "countries_reached": int(top.iloc[0]["countries_reached"]),
                          "country_weeks": int(top.iloc[0]["country_weeks"]),
                          "global_weeks": int(top.iloc[0]["global_weeks"])},
        "title_country_weeks_total": int(len(t["title_country_week"])),
    }
    audit.check(S, "kpis: travellers + others = cohort", len(trav) + len(rest) == len(cohort))
    audit.check(S, "kpis: kind split sums to cohort", int(by_kind["titles"].sum()) == len(cohort))
    audit.check(S, "kpis: debut bands sum to cohort", int(by_debut["titles"].sum()) == len(cohort))
    config.KPIS.write_text(json.dumps(kpis, indent=2, ensure_ascii=False) + "\n")
    log.info("headline: %d of %d non-English titles travel (%.1f%%)", len(trav), len(cohort), 100 * kpis["travel_rate"])
    marts = {"mart_by_kind": by_kind, "mart_by_debut_band": by_debut.astype({"debut_countries_band": str}),
             "mart_by_year": by_year, "mart_by_language": by_lang, "mart_weeks_to_peak": peak_dist,
             "mart_top_travellers": top}
    return {"kpis": kpis, "marts": marts, "titles": titles}

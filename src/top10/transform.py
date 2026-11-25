"""Stage 3 - TRANSFORM.

Turns the cleaned weekly lists into one row per non-English title (a film, or one TV season) with
the reach metrics the business question needs:

* global_weeks        weeks in the global non-English Top 10
* countries_reached   distinct countries whose national Top 10 it entered (any week in the window)
* country_weeks       sum over countries of weeks in that country's Top 10
* debut_countries     countries charting it in its first global week (early signal)
* weeks_to_peak       weeks from first global week to the week of its highest hours viewed
* language            original language from Wikidata, only when the match is unambiguous

and flags the analysis cohort (debut observed, >= FOLLOW_UP_WEEKS weeks of follow-up) and whether
the title "travels" (>= half of the countries Netflix reports AND >= MIN_GLOBAL_WEEKS global weeks).
"""
from __future__ import annotations

import logging
import math

import duckdb
import pandas as pd

from . import audit, config

log = logging.getLogger("transform")
S = "transform"


def countries_per_week(countries: pd.DataFrame) -> int:
    """Typical number of countries Netflix reports per week (median) - the reach denominator."""
    return int(countries.groupby("week")["country_iso2"].nunique().median())


def travel_threshold(n_countries: int) -> int:
    return math.ceil(config.MIN_COUNTRY_SHARE * n_countries)


def build_title_metrics(glob: pd.DataFrame, countries: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect()
    con.register("g", glob)
    con.register("c", countries)
    ne_rows = con.execute("select count(*) from g where is_non_english").fetchall()[0][0]
    title_week = con.execute("""
        select kind, show_title, season_title, coalesce(season_title, show_title) as title, week::date as week,
               weekly_rank, weekly_hours_viewed, weekly_views, cumulative_weeks_in_top_10, name_collision
        from g where is_non_english
        order by kind, show_title, season_title nulls first, week
    """).df()
    audit.stage(S, "global non-English rows -> title-week fact", len(glob), len(title_week),
                f"kept the {ne_rows:,} non-English rows")

    # country appearances of non-English titles; null-safe join on the full title key
    country_week = con.execute("""
        with ne_keys as (
            select distinct kind, show_title, season_title from g where is_non_english and not name_collision)
        select c.country_name, c.country_iso2, c.week::date as week, c.kind, c.show_title, c.season_title,
               coalesce(c.season_title, c.show_title) as title, c.weekly_rank
        from c join ne_keys k
          on c.kind = k.kind and c.show_title = k.show_title and c.season_title is not distinct from k.season_title
        order by kind, show_title, season_title nulls first, country_iso2, week
    """).df()
    audit.stage(S, "country rows -> non-English title-country-week fact", len(countries), len(country_week),
                "rows of English titles and of 6 name-collision keys left out")

    titles = con.execute(f"""
        with tw as (select * from title_week),
        gl as (
            select kind, show_title, season_title, any_value(title) as title, bool_or(name_collision) as name_collision,
                   min(week) as first_week, max(week) as last_week, count(*) as global_weeks,
                   min(weekly_rank) as best_rank, sum(weekly_hours_viewed) as hours_viewed_in_top10,
                   arg_min(cumulative_weeks_in_top_10, week) as cum_weeks_at_first_week,
                   arg_max(week, weekly_hours_viewed) as peak_week, max(weekly_hours_viewed) as peak_weekly_hours
            from tw group by kind, show_title, season_title),
        cw as (
            select kind, show_title, season_title, count(distinct country_iso2) as countries_reached,
                   count(*) as country_weeks, min(week) as first_country_week
            from country_week group by kind, show_title, season_title),
        wk as (
            select kind, show_title, season_title, week, count(*) as n_countries
            from country_week group by kind, show_title, season_title, week)
        select gl.*,
               coalesce(cw.countries_reached, 0) as countries_reached,
               coalesce(cw.country_weeks, 0) as country_weeks,
               coalesce((select n_countries from wk where wk.kind = gl.kind and wk.show_title = gl.show_title
                         and wk.season_title is not distinct from gl.season_title and wk.week = gl.first_week), 0)
                   as debut_countries,
               coalesce((select max(n_countries) from wk where wk.kind = gl.kind and wk.show_title = gl.show_title
                         and wk.season_title is not distinct from gl.season_title), 0) as max_countries_one_week,
               date_diff('week', gl.first_week, gl.peak_week) as weeks_to_peak,
               date_diff('week', gl.first_week, date '{config.AS_OF_WEEK}') as follow_up_weeks
        from gl left join cw on cw.kind = gl.kind and cw.show_title = gl.show_title
                             and cw.season_title is not distinct from gl.season_title
        order by gl.kind, gl.show_title, gl.season_title nulls first
    """).df()
    con.close()
    return title_week, country_week, titles


def flag_cohort(titles: pd.DataFrame, n_countries: int) -> pd.DataFrame:
    t = titles.copy()
    t["debut_observed"] = (t["cum_weeks_at_first_week"] == 1) & (pd.to_datetime(t["first_week"]) > pd.Timestamp(config.FIRST_WEEK))
    t["in_cohort"] = t["debut_observed"] & (t["follow_up_weeks"] >= config.FOLLOW_UP_WEEKS) & ~t["name_collision"]
    thr = travel_threshold(n_countries)
    t["travels"] = (t["countries_reached"] >= thr) & (t["global_weeks"] >= config.MIN_GLOBAL_WEEKS)
    t["debut_year"] = pd.to_datetime(t["first_week"]).dt.year
    t["debut_countries_band"] = pd.cut(t["debut_countries"], [-1, 9, 19, 39, 200],
                                       labels=["0-9", "10-19", "20-39", "40+"]).astype(str)
    n = len(t)
    audit.stage(S, "titles -> analysis cohort", n, int(t["in_cohort"].sum()),
                f"dropped {int((~t['debut_observed']).sum())} without an observed debut (already charting on "
                f"{config.FIRST_WEEK} or re-entries), {int((t['debut_observed'] & (t['follow_up_weeks'] < config.FOLLOW_UP_WEEKS)).sum())} "
                f"with < {config.FOLLOW_UP_WEEKS} weeks follow-up, {int((t['debut_observed'] & t['name_collision']).sum())} name collisions")
    audit.check(S, "titles: unique title key", not t.duplicated(["kind", "show_title", "season_title"]).any())
    audit.check(S, "titles: countries reached <= countries ever reported", (t["countries_reached"] <= 94).all())
    audit.check(S, "titles: weeks_to_peak within the title's run", (t["weeks_to_peak"] >= 0).all())
    unmatched = (t["countries_reached"] == 0) & ~t["name_collision"]
    audit.check(S, "titles: non-English titles found in no country list", True,
                f"{int(unmatched.sum())} titles charted globally but never in a national list under the same name",
                severity="info")
    return t


# ---------------------------------------------------------------- language (Wikidata)

def match_languages(titles: pd.DataFrame, wd: pd.DataFrame) -> pd.DataFrame:
    """Attach an original language per (kind, show_title), conservatively.

    Candidates are Wikidata items whose English label or alias equals the Netflix show title and
    that have an original language (P364). We keep only items of the right kind (TV = has seasons or
    episodes), with at least one non-English language; prefer Netflix-linked items; for films require
    a publication year no later than the debut year and no more than 5 years before it. If exactly one
    item survives we take its non-English language(s); otherwise the title stays 'Unmatched'.
    """
    wd = wd.copy()
    wd["year"] = pd.to_numeric(wd["year"], errors="coerce")
    shows = titles.groupby(["kind", "show_title"], as_index=False).agg(debut_year=("debut_year", "min"))
    out = []
    for r in shows.itertuples(index=False):
        c = wd[wd["label"] == r.show_title]
        c = c[c["has_seasons_or_episodes"] == (r.kind == "TV")]
        non_en = c[c["language"] != "English"]
        c = c[c["qid"].isin(non_en["qid"])]
        if c["netflix_linked"].any():
            c = c[c["netflix_linked"]]
        if r.kind == "Film":
            ok = c.groupby("qid")["year"].apply(lambda y: ((y <= r.debut_year) & (y >= r.debut_year - 5)).any())
            c = c[c["qid"].isin(ok[ok].index)]
        qids = c["qid"].unique()
        if len(qids) == 1:
            langs = sorted(set(c.loc[c["language"] != "English", "language"]))
            lang = langs[0] if len(langs) == 1 else "Multiple"
            status, qid = "matched", qids[0]
        else:
            lang, status, qid = "Unmatched", ("no candidate" if len(qids) == 0 else "ambiguous"), None
        out.append({"kind": r.kind, "show_title": r.show_title, "language": lang, "language_match": status,
                    "wikidata_qid": qid})
    m = pd.DataFrame(out)
    t = titles.merge(m, on=["kind", "show_title"], how="left", validate="many_to_one")
    cohort = t[t["in_cohort"]]
    audit.check(S, "language: Wikidata match coverage (cohort)", True,
                f"{(cohort['language_match'] == 'matched').mean():.1%} of {len(cohort)} cohort titles matched; "
                f"{(cohort['language_match'] == 'ambiguous').sum()} ambiguous, "
                f"{(cohort['language_match'] == 'no candidate').sum()} with no candidate", severity="info")
    return t


def run(staged: dict[str, pd.DataFrame] | None = None) -> dict[str, pd.DataFrame]:
    if staged is None:
        staged = {n: pd.read_parquet(config.STAGING / f"{n}.parquet") for n in ("global", "countries")}
    glob, countries = staged["global"], staged["countries"]
    n_countries = countries_per_week(countries)
    title_week, country_week, titles = build_title_metrics(glob, countries)
    titles = flag_cohort(titles, n_countries)
    wd = pd.read_csv(config.WIKIDATA_SNAPSHOT, dtype={"year": str})
    titles = match_languages(titles, wd)
    titles.attrs["n_countries"] = n_countries
    return {"title_week": title_week, "title_country_week": country_week, "titles": titles,
            "params": pd.DataFrame([{"as_of_week": config.AS_OF_WEEK, "countries_per_week": n_countries,
                                     "travel_min_countries": travel_threshold(n_countries),
                                     "travel_min_global_weeks": config.MIN_GLOBAL_WEEKS,
                                     "follow_up_weeks": config.FOLLOW_UP_WEEKS}])}

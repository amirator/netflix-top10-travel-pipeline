"""Stage 2 - CLEAN.

Reads the raw Netflix TSVs exactly as downloaded, types them, cuts them to the frozen study window
(<= config.AS_OF_WEEK) and runs data-quality checks. Every check and the row counts in/out of each
step are logged through `audit`. Output: two typed parquet files in data/staging/.

Nothing is silently dropped: rows removed by the window cut are counted, and known source quirks
(English/non-English title-name collisions, the country set changing over time, `weekly_views`
missing before mid-2023) are logged as warnings and handled explicitly in TRANSFORM.
"""
from __future__ import annotations

import logging

import pandas as pd

from . import audit, config

log = logging.getLogger("clean")
S = "clean"

GLOBAL_COLS = ["week", "category", "weekly_rank", "show_title", "season_title", "weekly_hours_viewed",
               "runtime", "weekly_views", "cumulative_weeks_in_top_10"]
COUNTRY_COLS = ["country_name", "country_iso2", "week", "category", "weekly_rank", "show_title", "season_title",
                "cumulative_weeks_in_top_10"]


def read_raw(name: str) -> pd.DataFrame:
    path = config.RAW / ("all-weeks-global.tsv" if name == "global" else "all-weeks-countries.tsv")
    # Netflix writes the literal string "N/A" for "not applicable"; nothing else should become NaN
    # (e.g. Namibia's ISO code "NA" must survive).
    return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, na_values=["N/A", ""])


def _common(df: pd.DataFrame, name: str, expected_cols: list[str]) -> pd.DataFrame:
    audit.check(S, f"{name}: expected columns", list(df.columns) == expected_cols, ", ".join(df.columns))
    n0 = len(df)
    df = df.copy()
    df["week"] = pd.to_datetime(df["week"], format="%Y-%m-%d", errors="coerce")
    audit.check(S, f"{name}: week parses as a date", df["week"].notna().all(), f"{df['week'].isna().sum()} unparsable")
    audit.check(S, f"{name}: every week is a Sunday", (df["week"].dt.day_of_week == 6).all())
    for col in ("weekly_rank", "cumulative_weeks_in_top_10"):
        df[col] = pd.to_numeric(df[col], errors="raise").astype("int64")
    df["show_title"] = df["show_title"].str.strip()
    df["season_title"] = df["season_title"].str.strip()
    audit.check(S, f"{name}: show_title never blank", df["show_title"].notna().all() and (df["show_title"] != "").all())
    in_window = (df["week"] >= pd.Timestamp(config.FIRST_WEEK)) & (df["week"] <= pd.Timestamp(config.AS_OF_WEEK))
    df = df[in_window].reset_index(drop=True)
    audit.stage(S, f"{name}: freeze study window {config.FIRST_WEEK}..{config.AS_OF_WEEK}", n0, len(df),
                f"{n0 - len(df):,} rows newer than AS_OF_WEEK held back")
    audit.check(S, f"{name}: rank between 1 and 10", df["weekly_rank"].between(1, 10).all())
    audit.check(S, f"{name}: cumulative weeks >= 1", (df["cumulative_weeks_in_top_10"] >= 1).all())
    weeks = pd.Series(sorted(df["week"].unique()))
    gaps = weeks.diff().dropna().dt.days
    audit.check(S, f"{name}: weeks contiguous (7-day steps)", (gaps == 7).all(),
                f"{len(weeks)} weeks, {weeks.min().date()}..{weeks.max().date()}")
    return df


def clean_global(raw: pd.DataFrame) -> pd.DataFrame:
    df = _common(raw, "global", GLOBAL_COLS)
    df["weekly_hours_viewed"] = pd.to_numeric(df["weekly_hours_viewed"], errors="raise").astype("int64")
    df["runtime"] = pd.to_numeric(df["runtime"], errors="coerce")
    df["weekly_views"] = pd.to_numeric(df["weekly_views"], errors="coerce").astype("Int64")
    cats = {"Films (English)", "Films (Non-English)", "TV (English)", "TV (Non-English)"}
    audit.check(S, "global: 4 known categories", set(df["category"]) == cats, ", ".join(sorted(set(df["category"]))))
    dup = df.duplicated(["week", "category", "weekly_rank"]).sum()
    audit.check(S, "global: unique (week, category, rank)", dup == 0, f"{dup} duplicates")
    per_list = df.groupby(["week", "category"]).size()
    audit.check(S, "global: every weekly list has exactly 10 rows", (per_list == 10).all(),
                f"{len(per_list)} weekly lists")
    audit.check(S, "global: hours viewed > 0", (df["weekly_hours_viewed"] > 0).all())
    # Until 2023-06-11 Netflix ranked each list by hours viewed; from 2023-06-18 it ranks by views
    # (hours / runtime), so each era is checked against its own ranking measure.
    srt = df.sort_values(["week", "category", "weekly_rank"])
    is_sorted = srt.groupby(["week", "category"])["weekly_hours_viewed"].apply(lambda s: s.is_monotonic_decreasing)
    early = is_sorted.index.get_level_values("week") < pd.Timestamp("2023-06-18")
    audit.check(S, "global: pre-2023-06-18 lists ranked by hours", bool(is_sorted[early].all()),
                f"{int(early.sum())} lists")
    views_sorted = srt[srt["week"] >= pd.Timestamp("2023-06-18")].groupby(["week", "category"])["weekly_views"].apply(
        lambda s: s.dropna().is_monotonic_decreasing)
    audit.check(S, "global: post-2023-06-18 lists ranked by views", bool(views_sorted.all()),
                f"{len(views_sorted)} lists")
    tv_no_season = ((df["category"].str.startswith("TV")) & df["season_title"].isna()).sum()
    audit.check(S, "global: TV rows carry a season_title", tv_no_season == 0, f"{tv_no_season} TV rows without one",
                severity="warn")
    first_views = df.loc[df["weekly_views"].notna(), "week"].min()
    missing_views = df["weekly_views"].isna().sum()
    audit.check(S, "global: weekly_views coverage", True,
                f"{missing_views:,} rows without views (Netflix added views from {first_views.date()}); "
                "hours viewed are used for all time-series metrics", severity="info")
    df["is_non_english"] = df["category"].str.contains("Non-English")
    df["kind"] = df["category"].str.startswith("Films").map({True: "Film", False: "TV"})
    # The country lists only say Films/TV, so a title key that appears in BOTH an English and a
    # non-English global list cannot be attributed in the country file. Flag it for TRANSFORM.
    key = ["kind", "show_title", "season_title"]
    langs = df.groupby(key, dropna=False)["is_non_english"].nunique()
    collisions = langs[langs > 1].reset_index()[key]
    df = df.merge(collisions.assign(name_collision=True), on=key, how="left")
    df["name_collision"] = df["name_collision"].fillna(False).astype(bool)
    audit.check(S, "global: English/non-English title-name collisions", True,
                f"{len(collisions)} keys ({', '.join(collisions['show_title'])}) flagged and excluded from country metrics",
                severity="info")
    return df


def clean_countries(raw: pd.DataFrame) -> pd.DataFrame:
    df = _common(raw, "countries", COUNTRY_COLS)
    audit.check(S, "countries: 2 known categories", set(df["category"]) == {"Films", "TV"})
    audit.check(S, "countries: ISO2 codes are 2 letters", df["country_iso2"].str.fullmatch(r"[A-Z]{2}").all())
    dup = df.duplicated(["country_iso2", "week", "category", "weekly_rank"]).sum()
    audit.check(S, "countries: unique (country, week, category, rank)", dup == 0, f"{dup} duplicates")
    per_list = df.groupby(["country_iso2", "week", "category"]).size()
    audit.check(S, "countries: every list has exactly 10 rows", (per_list == 10).all(), f"{len(per_list):,} lists")
    per_week = df.groupby("week")["country_iso2"].nunique()
    n_countries = df["country_iso2"].nunique()
    partial = df.groupby(["country_iso2", "country_name"])["week"].nunique()
    partial = partial[partial < df["week"].nunique()]
    audit.check(S, "countries: country set over time", True,
                f"{n_countries} countries ever; {per_week.min()}-{per_week.max()} per week; partial coverage: "
                + "; ".join(f"{n} ({w} weeks)" for (_, n), w in partial.items()), severity="info")
    df["kind"] = df["category"].map({"Films": "Film", "TV": "TV"})
    return df


def run() -> dict[str, pd.DataFrame]:
    out = {}
    for name, fn in (("global", clean_global), ("countries", clean_countries)):
        raw = read_raw(name)
        df = fn(raw)
        audit.stage(S, f"{name}: raw -> staging", len(raw), len(df))
        config.STAGING.mkdir(parents=True, exist_ok=True)
        df.to_parquet(config.STAGING / f"{name}.parquet", index=False)
        out[name] = df
    if audit.failures():
        raise RuntimeError(f"data-quality checks failed: {audit.failures()}")
    return out


if __name__ == "__main__":
    config.setup_logging()
    run()
    audit.write()

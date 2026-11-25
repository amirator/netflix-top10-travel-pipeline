import json

import pandas as pd
import pytest

from top10 import config

TABLES = {"dim_title", "fct_title_week", "fct_title_country_week", "mart_by_kind", "mart_by_debut_band",
          "mart_by_year", "mart_by_language", "mart_weeks_to_peak", "mart_top_travellers", "params",
          "meta_extract_manifest", "meta_kpis", "audit_stage_rows", "audit_quality_checks"}


def test_all_tables_in_duckdb_and_parquet(db):
    names = {r[0] for r in db.execute("show tables").fetchall()}
    assert TABLES <= names
    for t in TABLES:
        n_db = db.execute(f"select count(*) from {t}").fetchall()[0][0]
        n_pq = len(pd.read_parquet(config.WAREHOUSE / "parquet" / f"{t}.parquet"))
        assert n_db == n_pq, t


def test_warehouse_kpis_equal_kpis_json(db, kpis):
    stored = {k: json.loads(v) for k, v in db.execute("select key, value from meta_kpis").fetchall()}
    assert stored == kpis


def test_dim_title_grain_and_ranges(db):
    dup = db.execute("""select count(*) from (select kind, show_title, season_title, count(*) n from dim_title
                        group by all having n > 1)""").fetchall()[0][0]
    assert dup == 0
    bad = db.execute("""select count(*) from dim_title where countries_reached > 94 or debut_countries > countries_reached
                        or weeks_to_peak < 0 or global_weeks < 1""").fetchall()[0][0]
    assert bad == 0


def test_marts_sum_to_cohort(db, kpis):
    for mart in ("mart_by_kind", "mart_by_debut_band", "mart_by_year"):
        assert db.execute(f"select sum(titles) from {mart}").fetchall()[0][0] == kpis["cohort_titles"], mart
        assert db.execute(f"select sum(travellers) from {mart}").fetchall()[0][0] == kpis["travellers"], mart


def test_streamlit_app_renders_without_exceptions(db):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(config.ROOT / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, at.exception
    assert at.title[0].value.startswith("Which non-English Netflix titles travel")
    assert len(at.metric) >= 4

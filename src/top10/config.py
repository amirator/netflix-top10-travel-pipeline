"""Paths, source URLs and analysis parameters shared by every stage."""
from __future__ import annotations

import logging
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
RAW = DATA / "raw"                 # Netflix files: downloaded, never committed (Tudum terms of use)
REFERENCE = DATA / "reference"     # Wikidata snapshot (CC0): committed for reproducibility
STAGING = DATA / "staging"         # cleaned parquet
WAREHOUSE = DATA / "warehouse"     # DuckDB + parquet marts read by the Streamlit app
DB_PATH = WAREHOUSE / "top10.duckdb"
MANIFEST = RAW / "manifest.json"
KPIS = ROOT / "kpis.json"
QUALITY_LOG = DATA / "quality_log.json"

SOURCE_PAGE = "https://www.netflix.com/tudum/top10"
TERMS_URL = "https://help.netflix.com/legal/tudumtermsofuse"
SOURCES = {
    "global": "https://www.netflix.com/tudum/top10/data/all-weeks-global.tsv",
    "countries": "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv",
}
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
WIKIDATA_SNAPSHOT = REFERENCE / "wikidata_candidates.csv"
NETFLIX_QID = "Q907311"
USER_AGENT = "netflix-top10-travel-pipeline/1.0 (https://github.com/amirator/netflix-top10-travel-pipeline)"

# Analysis window. Netflix appends a new week every Tuesday; we freeze the study at this week so
# the README numbers stay reproducible. Bump it (and re-run) to refresh the study.
FIRST_WEEK = "2021-07-04"          # first week Netflix publishes
AS_OF_WEEK = "2026-11-22"
# A title enters the cohort only if we see its debut (global cumulative weeks == 1 on its first
# observed week, and that week is after FIRST_WEEK) and we can follow it for >= FOLLOW_UP_WEEKS.
FOLLOW_UP_WEEKS = 12

# "Travels" definition (see README): charted in at least half of the countries Netflix reports
# AND spent at least MIN_GLOBAL_WEEKS weeks in the global non-English Top 10.
MIN_COUNTRY_SHARE = 0.5
MIN_GLOBAL_WEEKS = 4

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

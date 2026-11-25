"""Stage 5 - LOAD.

Writes every table to a DuckDB warehouse (data/warehouse/top10.duckdb) and to Parquet
(data/warehouse/parquet/<table>.parquet). The Streamlit app reads only from the warehouse.
The run audit (row counts per stage, data-quality checks) and the extract manifest are loaded too,
so lineage is queryable next to the data.
"""
from __future__ import annotations

import json
import logging

import duckdb
import pandas as pd

from . import audit, config

log = logging.getLogger("load")
S = "load"


def run(t: dict[str, pd.DataFrame], a: dict) -> dict[str, int]:
    tables: dict[str, pd.DataFrame] = {
        "dim_title": a["titles"],
        "fct_title_week": t["title_week"],
        "fct_title_country_week": t["title_country_week"],
        "params": t["params"],
        **a["marts"],
    }
    manifest = json.loads(config.MANIFEST.read_text())["files"]
    tables["meta_extract_manifest"] = pd.DataFrame(manifest)
    tables["meta_kpis"] = pd.DataFrame([{"key": k, "value": json.dumps(v, ensure_ascii=False)} for k, v in a["kpis"].items()])

    pq_dir = config.WAREHOUSE / "parquet"
    pq_dir.mkdir(parents=True, exist_ok=True)
    tmp_db = config.DB_PATH.with_suffix(".duckdb.tmp")
    tmp_db.unlink(missing_ok=True)
    counts = {}
    with duckdb.connect(str(tmp_db)) as con:
        for name, df in tables.items():
            df = df.copy()
            for col in df.columns:  # parquet/duckdb friendly types
                if df[col].dtype == "object" and df[col].map(type).eq(bool).any():
                    df[col] = df[col].astype("boolean")
            con.register("df_view", df)
            con.execute(f"create or replace table {name} as select * from df_view").fetchall()
            con.unregister("df_view")
            con.execute(f"copy {name} to '{pq_dir / (name + '.parquet')}' (format parquet)").fetchall()
            counts[name] = con.execute(f"select count(*) from {name}").fetchall()[0][0]
            audit.check(S, f"{name}: rows written == rows in", counts[name] == len(df), f"{counts[name]:,} rows")
        audit.stage(S, "tables -> DuckDB + Parquet", sum(len(d) for d in tables.values()), sum(counts.values()),
                    f"{len(tables)} tables")
        stages = pd.DataFrame(audit.STAGES)
        checks = pd.DataFrame(audit.CHECKS)
        for name, df in (("audit_stage_rows", stages), ("audit_quality_checks", checks)):
            con.register("df_view", df)
            con.execute(f"create or replace table {name} as select * from df_view").fetchall()
            con.unregister("df_view")
            con.execute(f"copy {name} to '{pq_dir / (name + '.parquet')}' (format parquet)").fetchall()
    tmp_db.replace(config.DB_PATH)  # atomic swap so a running dashboard never sees a half-written file
    log.info("warehouse written: %s (%d tables)", config.DB_PATH.relative_to(config.ROOT), len(counts) + 2)
    return counts

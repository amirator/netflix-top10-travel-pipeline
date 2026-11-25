"""Render README.md from docs/README.template.md + kpis.json + the run audit (single source of numbers)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render() -> str:
    k = json.loads((ROOT / "kpis.json").read_text())
    q = json.loads((ROOT / "data" / "quality_log.json").read_text())
    import duckdb
    with duckdb.connect(str(ROOT / "data/warehouse/top10.duckdb"), read_only=True) as con:
        band = con.execute("select * from mart_by_debut_band").df().set_index("debut_countries_band").loc[
            ["0-9", "10-19", "20-39", "40+"]]
    band_rows = "\n".join(f"| {b} | {int(r.titles):,} | {pct(r.travel_rate)} ({int(r.travellers)}) |"
                          for b, r in band.iterrows())
    lang = sorted(((n, v) for n, v in k["language_rates"].items()), key=lambda x: -x[1]["travel_rate"])
    lang_rows = "\n".join(f"| {n} | {v['titles']} | {v['travellers']} | {pct(v['travel_rate'])} |" for n, v in lang)
    module = {"clean": "clean.py", "transform": "transform.py", "analyze": "analyze.py", "load": "load.py"}
    stage_rows = "| 1 Extract | `extract.py` | Download the 2 Netflix files and the Wikidata snapshot; write the manifest | 2 files |\n"
    stage_rows += "\n".join(f"| {s['stage'].title()} | `{module[s['stage']]}` | {s['step']} | {s['rows_in']:,} → {s['rows_out']:,} |"
                            for s in q["stages"])
    status = [c["status"] for c in q["checks"]]
    v = {
        **{key: val for key, val in k.items() if not isinstance(val, dict)},
        "others": f"{k['cohort_titles'] - k['travellers']:,}",
        "cohort_titles": f"{k['cohort_titles']:,}", "cohort_films": f"{k['cohort_films']:,}",
        "band_rows": band_rows, "lang_rows": lang_rows, "stage_rows": stage_rows,
        "top_title": k["top_traveller"]["title"], "top_countries": k["top_traveller"]["countries_reached"],
        "top_country_weeks": f"{k['top_traveller']['country_weeks']:,}", "top_global_weeks": k["top_traveller"]["global_weeks"],
        "hindi": "{travellers} of {titles}".format(**k["language_rates"]["Hindi"]),
        "telugu": "{travellers} of {titles}".format(**k["language_rates"]["Telugu"]),
        "checks_pass": status.count("pass"), "checks_warn": status.count("warn"), "checks_info": status.count("info"),
    }
    for key in ("travel_rate", "travel_rate_tv", "travel_rate_film", "debut_40plus_travel_rate", "debut_under10_travel_rate",
                "travellers_from_40plus_debut_share", "travellers_peak_by_week2_share", "others_peak_by_week2_share",
                "language_matched_share", "unmatched_travel_rate"):
        v[key] = pct(k[key])
    for key in ("median_debut_countries_travellers", "median_debut_countries_others", "median_countries_travellers",
                "median_countries_others", "median_global_weeks_travellers", "median_global_weeks_others"):
        v[key] = f"{k[key]:g}"
    return Template((ROOT / "docs" / "README.template.md").read_text()).substitute(v)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        sys.exit(0 if (ROOT / "README.md").read_text() == text else 1)
    (ROOT / "README.md").write_text(text)
    print("README.md written")

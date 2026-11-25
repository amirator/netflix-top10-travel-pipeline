"""Streamlit dashboard - the LOAD target of the pipeline. Reads only from data/warehouse/top10.duckdb.

    streamlit run streamlit_app.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "warehouse" / "top10.duckdb"
RED, GREY, DARK = "#E50914", "#B3B3B3", "#221F1F"

st.set_page_config(page_title="Which non-English Netflix titles travel?", page_icon="🌍", layout="wide")


@st.cache_resource(show_spinner="First run: building the warehouse from Netflix's Top 10 files (~30 s)...")
def ensure_warehouse() -> str:
    if not DB.exists():  # e.g. a fresh Streamlit Cloud container: run the pipeline once
        subprocess.run([sys.executable, str(ROOT / "run_pipeline.py")], check=True, cwd=ROOT)
    return str(DB)


@st.cache_data
def q(sql: str) -> pd.DataFrame:
    with duckdb.connect(ensure_warehouse(), read_only=True) as con:
        return con.execute(sql).df()


k = {r.key: json.loads(r.value) for r in q("select key, value from meta_kpis").itertuples()}
pct = lambda x: f"{100 * x:.1f}%"  # noqa: E731

st.title("Which non-English Netflix titles travel?")
st.caption(
    f"Netflix's official weekly Top 10 lists, {k['first_week']} to {k['as_of_week']} ({k['weeks_in_study']} weeks, "
    f"{k['countries_per_week']} countries a week). A title **travels** if it charts in at least "
    f"{k['travel_min_countries']} countries and spends {k['travel_min_global_weeks']}+ weeks in the global non-English Top 10."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Non-English titles studied", f"{k['cohort_titles']:,}", help="Debut observed, 12+ weeks of follow-up")
c2.metric("Titles that travel", f"{k['travellers']:,} ({pct(k['travel_rate'])})")
c3.metric("TV seasons vs films that travel", f"{pct(k['travel_rate_tv'])} vs {pct(k['travel_rate_film'])}")
c4.metric("Travel if 40+ / under 10 debut countries",
          f"{pct(k['debut_40plus_travel_rate'])} / {pct(k['debut_under10_travel_rate'])}")

tab1, tab2, tab3, tab4 = st.tabs(["What travellers share", "Title explorer", "Top travellers", "Pipeline & data quality"])

with tab1:
    a, b = st.columns(2)
    band = q("select * from mart_by_debut_band order by debut_countries_band = '0-9' desc, debut_countries_band")
    fig = px.bar(band, x="debut_countries_band", y="travel_rate", text=band["travel_rate"].map(pct),
                 labels={"debut_countries_band": "Countries charting it in its debut week", "travel_rate": "Share that travel"},
                 color_discrete_sequence=[RED], title="Debut-week breadth is the strongest early signal")
    fig.update_yaxes(tickformat=".0%")
    a.plotly_chart(fig, use_container_width=True)
    a.caption("n = " + ", ".join(f"{r.debut_countries_band}: {r.titles}" for r in band.itertuples()) + " titles")

    lang = q("select * from mart_by_language order by travel_rate")
    fig = px.bar(lang, y="language_group", x="travel_rate", orientation="h", text=lang["travel_rate"].map(pct),
                 hover_data=["titles", "travellers"], color_discrete_sequence=[DARK],
                 labels={"language_group": "", "travel_rate": "Share that travel"},
                 title=f"Travel rate by original language ({k['language_matched_titles']:,} titles matched in Wikidata)")
    fig.update_xaxes(tickformat=".0%")
    fig.update_traces(textposition="outside", textfont_size=12)
    fig.update_xaxes(range=[0, lang["travel_rate"].max() * 1.18])
    b.plotly_chart(fig, use_container_width=True)
    b.caption(f"Language from Wikidata, kept only when the match is unambiguous ({pct(k['language_matched_share'])} "
              f"of titles). Unmatched titles travel {pct(k['unmatched_travel_rate'])} of the time, so matched titles skew "
              "towards better-known ones.")

    a, b = st.columns(2)
    kind = q("select * from mart_by_kind")
    fig = px.bar(kind, x="kind", y="travel_rate", text=kind["travel_rate"].map(pct), color="kind",
                 color_discrete_map={"TV": RED, "Film": DARK}, labels={"kind": "", "travel_rate": "Share that travel"},
                 title="TV seasons travel more often than films")
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(showlegend=False)
    a.plotly_chart(fig, use_container_width=True)

    year = q("select * from mart_by_year order by debut_year")
    fig = px.bar(year, x="debut_year", y=["travellers"], text="travellers", color_discrete_sequence=[RED],
                 labels={"debut_year": "Debut year", "value": "Titles that travel"},
                 title="Travellers by debut year")
    fig.update_layout(showlegend=False)
    b.plotly_chart(fig, use_container_width=True)
    b.caption("2021 starts on 4 July; 2026 titles need 12 weeks of follow-up, so the last year is partial.")

    peak = q("select * from mart_weeks_to_peak")
    peak["group"] = peak["travels"].map({True: "Travellers", False: "Other titles"})
    peak["share"] = peak["titles"] / peak.groupby("group")["titles"].transform("sum")
    order = ["debut week", "week 2", "week 3", "week 4", "week 5+"]
    fig = px.bar(peak, x="peak_bucket", y="share", color="group", barmode="group", category_orders={"peak_bucket": order},
                 color_discrete_map={"Travellers": RED, "Other titles": GREY},
                 labels={"peak_bucket": "Week of peak hours viewed (global list)", "share": "Share of titles", "group": ""},
                 title="Weeks to peak: almost everything peaks in its first two weeks")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    titles = q("""select title, kind, language_group, first_week, global_weeks, countries_reached, country_weeks,
                  debut_countries, weeks_to_peak, travels, in_cohort from dim_title order by country_weeks desc""")
    pick = st.selectbox("Title (sorted by country-weeks in national Top 10s)", titles["title"].tolist())
    row = titles[titles["title"] == pick].iloc[0]
    m = st.columns(5)
    m[0].metric("Countries reached", int(row.countries_reached))
    m[1].metric("Country-weeks", f"{int(row.country_weeks):,}")
    m[2].metric("Weeks in global Top 10", int(row.global_weeks))
    m[3].metric("Debut-week countries", int(row.debut_countries))
    m[4].metric("Travels?", "Yes" if row.travels else "No")
    safe = pick.replace("'", "''")
    weekly = q(f"""select week, count(*) as countries from fct_title_country_week where title = '{safe}'
                   group by week order by week""")
    glob = q(f"select week, weekly_rank from fct_title_week where title = '{safe}' order by week")
    a, b = st.columns([3, 2])
    fig = px.bar(weekly, x="week", y="countries", color_discrete_sequence=[RED],
                 title="Countries with it in their national Top 10, by week")
    a.plotly_chart(fig, use_container_width=True)
    reach = q(f"""select country_name, count(*) as weeks from fct_title_country_week where title = '{safe}'
                  group by country_name""")
    fig = px.choropleth(reach, locations="country_name", locationmode="country names", color="weeks",
                        color_continuous_scale="Reds", title="Weeks in each country's Top 10")
    fig.update_layout(margin=dict(l=0, r=0, t=40, b=0))
    b.plotly_chart(fig, use_container_width=True)
    st.caption(f"Global non-English Top 10 rank by week: " + ", ".join(
        f"{w:%d %b %Y} #{r}" for w, r in zip(pd.to_datetime(glob["week"]), glob["weekly_rank"])))

with tab3:
    top = q("select * from mart_top_travellers")
    st.dataframe(top, use_container_width=True, hide_index=True,
                 column_config={"language_group": "language", "first_week": st.column_config.DateColumn("debut week")})
    st.caption("Ranked by country-weeks: the sum over countries of weeks spent in that country's Top 10.")

with tab4:
    st.markdown("**EXTRACT -> CLEAN -> TRANSFORM -> ANALYZE -> LOAD -> this dashboard**")
    man = q("select name, source_url, downloaded_at_utc, bytes, data_rows, sha256 from meta_extract_manifest")
    st.subheader("Extract manifest")
    st.dataframe(man, use_container_width=True, hide_index=True)
    a, b = st.columns(2)
    a.subheader("Rows in / out per stage")
    a.dataframe(q("select * from audit_stage_rows"), use_container_width=True, hide_index=True)
    b.subheader("Data-quality checks")
    b.dataframe(q("select * from audit_quality_checks"), use_container_width=True, hide_index=True)

st.divider()
st.caption("Data: Netflix Top 10 (netflix.com/tudum/top10, Tudum terms of use) and Wikidata (CC0). "
           "Top 10 lists show what charted, not total viewing. Built by "
           "[Mohammad Amir Khan](https://github.com/amirator) - initial prototype.")

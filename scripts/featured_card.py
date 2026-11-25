"""Render docs/featured_card.png (1200x627, LinkedIn Featured size) from kpis.json + the warehouse."""
import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
k = json.loads((ROOT / "kpis.json").read_text())
with duckdb.connect(str(ROOT / "data/warehouse/top10.duckdb"), read_only=True) as con:
    band = con.execute("select debut_countries_band, travel_rate, titles from mart_by_debut_band").df()
band = band.set_index("debut_countries_band").loc[["0-9", "10-19", "20-39", "40+"]].reset_index()

RED, DARK, GREY = "#E50914", "#141414", "#9A9A9A"
fig = plt.figure(figsize=(12, 6.27), dpi=100, facecolor=DARK)
fig.text(0.04, 0.88, "Which non-English Netflix titles travel?", color="white", fontsize=27, weight="bold")
fig.text(0.04, 0.815, "Python ETL pipeline (extract > clean > transform > analyze > load) into a Streamlit dashboard",
         color=GREY, fontsize=13.5)
bullets = [
    f"{k['travellers']} of {k['cohort_titles']:,} non-English titles ({100*k['travel_rate']:.1f}%) charted in "
    f"{k['travel_min_countries']}+ countries\nand {k['travel_min_global_weeks']}+ weeks in the global Top 10",
    f"Debut in 40+ countries: {100*k['debut_40plus_travel_rate']:.1f}% went on to travel,\n"
    f"vs {100*k['debut_under10_travel_rate']:.1f}% for titles debuting in under 10",
    f"TV seasons travel more than films: {100*k['travel_rate_tv']:.1f}% vs {100*k['travel_rate_film']:.1f}%;\n"
    f"{k['title_country_weeks_total']:,} country-weeks reconciled to Netflix's raw files",
]
y = 0.66
for b in bullets:
    fig.text(0.04, y, "■", color=RED, fontsize=13, va="top")
    fig.text(0.07, y, b, color="white", fontsize=14.5, va="top", linespacing=1.35)
    y -= 0.165
fig.text(0.04, 0.085, "Python · pandas · DuckDB · Parquet · Streamlit · Plotly · pytest · GitHub Actions",
         color=GREY, fontsize=12.5)
fig.text(0.04, 0.035, f"Data: Netflix Top 10 (Tudum), {k['first_week']} to {k['as_of_week']} · Mohammad Amir Khan · "
         "github.com/amirator", color=GREY, fontsize=10.5)

ax = fig.add_axes([0.66, 0.22, 0.31, 0.5], facecolor=DARK)
bars = ax.bar(band["debut_countries_band"], band["travel_rate"] * 100,
              color=[GREY, GREY, GREY, RED], width=0.65)
for bar, v in zip(bars, band["travel_rate"] * 100):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 1.5, f"{v:.1f}%", ha="center", color="white", fontsize=12, weight="bold")
ax.set_ylim(0, 70)
ax.set_yticks([])
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(GREY)
ax.tick_params(colors="white", labelsize=12)
ax.set_xlabel("Countries charting it in its debut week", color=GREY, fontsize=11)
ax.set_title("Share that went on to travel", color="white", fontsize=13, loc="left")
out = ROOT / "docs" / "featured_card.png"
fig.savefig(out, facecolor=DARK)
print("saved", out)

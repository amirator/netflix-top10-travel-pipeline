"""Stage 1 - EXTRACT.

Downloads Netflix's official Top 10 files from Tudum and records, for every file, the source URL,
download time (UTC), size and SHA-256 in data/raw/manifest.json. Raw files are kept byte-for-byte
as downloaded and are never committed (they are Netflix's, under the Tudum terms of use).

Also pulls the original language of each non-English title from Wikidata (CC0) with one SPARQL
query per batch of titles. That result is snapshotted to data/reference/ so a run is reproducible
without hitting Wikidata again; pass refresh_wikidata=True to re-query.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import logging
import time
from pathlib import Path

import requests

from . import config

log = logging.getLogger("extract")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def download(name: str, url: str, dest_dir: Path = config.RAW, retries: int = 3) -> dict:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(url).name
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=120, stream=True) as r:
                r.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                tmp.replace(dest)
            break
        except requests.RequestException as exc:  # pragma: no cover - network
            log.warning("download %s failed (attempt %d/%d): %s", url, attempt, retries, exc)
            if attempt == retries:
                raise
            time.sleep(5 * attempt)
    with dest.open("rb") as f:
        rows = sum(1 for _ in f) - 1  # minus header
    entry = {
        "name": name,
        "source_url": url,
        "landing_page": config.SOURCE_PAGE,
        "terms": config.TERMS_URL,
        "file": str(dest.relative_to(config.ROOT)),
        "downloaded_at_utc": _utc_now(),
        "bytes": dest.stat().st_size,
        "sha256": sha256(dest),
        "data_rows": rows,
    }
    log.info("downloaded %s: %s rows, %s bytes, sha256 %s", name, f"{rows:,}", f"{entry['bytes']:,}", entry["sha256"][:12])
    return entry


# ---------------------------------------------------------------- Wikidata (original language)

SPARQL = """
SELECT ?lbl ?item ?langLabel ?year ?netflix ?series WHERE {{
  VALUES ?lbl {{ {values} }}
  {{ ?item rdfs:label ?lbl }} UNION {{ ?item skos:altLabel ?lbl }}
  ?item wdt:P364 ?lang .
  OPTIONAL {{ ?item wdt:P577 ?date . BIND(YEAR(?date) AS ?year) }}
  BIND(EXISTS {{ {{ ?item wdt:P750 wd:{nf} }} UNION {{ ?item wdt:P449 wd:{nf} }} UNION {{ ?item wdt:P272 wd:{nf} }} }} AS ?netflix)
  BIND(EXISTS {{ {{ ?item wdt:P1113 [] }} UNION {{ ?item wdt:P2437 [] }} }} AS ?series)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}}"""
WD_FIELDS = ["label", "qid", "language", "year", "netflix_linked", "has_seasons_or_episodes"]


def _sparql_batch(labels: list[str]) -> list[dict]:
    values = " ".join(json.dumps(l) + "@en" for l in labels)
    q = SPARQL.format(values=values, nf=config.NETFLIX_QID)
    for attempt in range(1, 5):
        r = requests.post(
            config.WIKIDATA_SPARQL,
            data={"query": q},
            headers={"Accept": "application/sparql-results+json", "User-Agent": config.USER_AGENT},
            timeout=180,
        )
        if r.status_code == 200:
            break
        log.warning("wikidata HTTP %s (attempt %d)", r.status_code, attempt)  # pragma: no cover
        time.sleep(10 * attempt)  # pragma: no cover
    r.raise_for_status()
    out = []
    for b in r.json()["results"]["bindings"]:
        out.append({
            "label": b["lbl"]["value"],
            "qid": b["item"]["value"].rsplit("/", 1)[-1],
            "language": b["langLabel"]["value"],
            "year": b.get("year", {}).get("value", ""),
            "netflix_linked": b["netflix"]["value"] == "true",
            "has_seasons_or_episodes": b["series"]["value"] == "true",
        })
    return out


def non_english_show_titles(global_tsv: Path) -> list[str]:
    titles = set()
    with global_tsv.open(encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if "Non-English" in row["category"]:
                titles.add(row["show_title"])
    return sorted(titles)


def extract_wikidata(labels: list[str], batch: int = 120) -> Path:
    rows: list[dict] = []
    for i in range(0, len(labels), batch):
        rows.extend(_sparql_batch(labels[i : i + batch]))
        time.sleep(1)
    rows = sorted({tuple(r[k] for k in WD_FIELDS) for r in rows})  # de-duplicate (year x lang fan-out)
    config.REFERENCE.mkdir(parents=True, exist_ok=True)
    with config.WIKIDATA_SNAPSHOT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(WD_FIELDS)
        w.writerows(rows)
    meta = {"queried_at_utc": _utc_now(), "endpoint": config.WIKIDATA_SPARQL, "labels_queried": len(labels),
            "candidate_rows": len(rows), "licence": "CC0 1.0 (Wikidata)"}
    (config.REFERENCE / "wikidata_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    log.info("wikidata: %d labels -> %d candidate rows", len(labels), len(rows))
    return config.WIKIDATA_SNAPSHOT


def run(offline: bool = False, refresh_wikidata: bool = False) -> dict:
    """Download (or reuse with offline=True) the Netflix files and write the manifest."""
    entries = []
    for name, url in config.SOURCES.items():
        dest = config.RAW / Path(url).name
        if offline and dest.exists():
            prev = {}
            if config.MANIFEST.exists():
                prev = {e["name"]: e for e in json.loads(config.MANIFEST.read_text())["files"]}
            entry = prev.get(name) or {"name": name, "source_url": url, "file": str(dest.relative_to(config.ROOT)),
                                       "downloaded_at_utc": None, "bytes": dest.stat().st_size}
            entry["sha256"] = sha256(dest)
            log.info("offline: reusing %s (sha256 %s)", dest.name, entry["sha256"][:12])
            entries.append(entry)
        else:
            entries.append(download(name, url))
    if refresh_wikidata or not config.WIKIDATA_SNAPSHOT.exists():
        extract_wikidata(non_english_show_titles(config.RAW / "all-weeks-global.tsv"))
    wd_meta = json.loads((config.REFERENCE / "wikidata_meta.json").read_text())
    entries.append({
        "name": "wikidata_languages",
        "source_url": config.WIKIDATA_SPARQL,
        "file": str(config.WIKIDATA_SNAPSHOT.relative_to(config.ROOT)),
        "downloaded_at_utc": wd_meta["queried_at_utc"],
        "bytes": config.WIKIDATA_SNAPSHOT.stat().st_size,
        "sha256": sha256(config.WIKIDATA_SNAPSHOT),
        "data_rows": wd_meta["candidate_rows"],
        "licence": wd_meta["licence"],
    })
    manifest = {"generated_at_utc": _utc_now(), "files": entries}
    config.RAW.mkdir(parents=True, exist_ok=True)
    config.MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    config.setup_logging()
    run()

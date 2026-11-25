"""Run the whole pipeline: EXTRACT -> CLEAN -> TRANSFORM -> ANALYZE -> LOAD.

    python run_pipeline.py              # download fresh Netflix files, run everything
    python run_pipeline.py --offline    # reuse files already in data/raw/
    python run_pipeline.py --refresh-wikidata   # also re-query Wikidata for languages
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from top10 import analyze, audit, clean, config, extract, load, transform  # noqa: E402

log = logging.getLogger("pipeline")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--offline", action="store_true", help="reuse raw files already downloaded")
    p.add_argument("--refresh-wikidata", action="store_true", help="re-query Wikidata for original languages")
    args = p.parse_args(argv)
    config.setup_logging()
    audit.reset()
    t0 = time.time()
    steps = []

    def timed(name, fn, *a, **kw):
        s = time.time()
        out = fn(*a, **kw)
        steps.append((name, time.time() - s))
        return out

    timed("extract", extract.run, offline=args.offline, refresh_wikidata=args.refresh_wikidata)
    staged = timed("clean", clean.run)
    t = timed("transform", transform.run, staged)
    a = timed("analyze", analyze.run, t)
    timed("load", load.run, t, a)
    audit.write()
    for name, secs in steps:
        log.info("%-9s %6.1fs", name, secs)
    k = a["kpis"]
    log.info("DONE in %.1fs - %d of %d non-English titles travel (%.1f%%); checks: %d pass, %d warn, %d info, %d fail",
             time.time() - t0, k["travellers"], k["cohort_titles"], 100 * k["travel_rate"],
             sum(c["status"] == "pass" for c in audit.CHECKS), sum(c["status"] == "warn" for c in audit.CHECKS), sum(c["status"] == "info" for c in audit.CHECKS),
             len(audit.failures()))
    return 1 if audit.failures() else 0


if __name__ == "__main__":
    raise SystemExit(main())

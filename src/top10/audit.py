"""Tiny run audit shared by all stages: row counts in/out per stage and data-quality checks.

Everything recorded here ends up in data/quality_log.json and in the DuckDB table
`audit_quality_checks` / `audit_stage_rows`, so the dashboard can show it.
"""
from __future__ import annotations

import json
import logging

from . import config

log = logging.getLogger("audit")
STAGES: list[dict] = []
CHECKS: list[dict] = []


def reset() -> None:
    STAGES.clear()
    CHECKS.clear()


def stage(stage: str, step: str, rows_in: int, rows_out: int, note: str = "") -> None:
    STAGES.append({"stage": stage, "step": step, "rows_in": int(rows_in), "rows_out": int(rows_out), "note": note})
    log.info("[%s] %s: %s rows in -> %s rows out %s", stage, step, f"{rows_in:,}", f"{rows_out:,}", note)


def check(stage: str, name: str, passed: bool, detail: str = "", severity: str = "error") -> bool:
    if severity == "info":
        status = "info"  # a recorded observation about the source, not a pass/fail test
    else:
        status = "pass" if passed else ("fail" if severity == "error" else "warn")
    CHECKS.append({"stage": stage, "check": name, "status": status, "detail": detail})
    (log.info if passed else log.warning)("[%s] check %-45s %s %s", stage, name, status.upper(), detail)
    return passed


def failures() -> list[dict]:
    return [c for c in CHECKS if c["status"] == "fail"]


def write() -> None:
    config.QUALITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    config.QUALITY_LOG.write_text(json.dumps({"stages": STAGES, "checks": CHECKS}, indent=2, ensure_ascii=False) + "\n")

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from top10 import config  # noqa: E402


def _need(path: Path):
    if not path.exists():
        pytest.skip(f"{path.relative_to(ROOT)} missing - run `python run_pipeline.py` first")


@pytest.fixture(scope="session")
def kpis():
    _need(config.KPIS)
    return json.loads(config.KPIS.read_text())


@pytest.fixture(scope="session")
def raw_paths():
    g, c = config.RAW / "all-weeks-global.tsv", config.RAW / "all-weeks-countries.tsv"
    _need(g)
    _need(c)
    return g, c


@pytest.fixture(scope="session")
def db():
    import duckdb
    _need(config.DB_PATH)
    con = duckdb.connect(str(config.DB_PATH), read_only=True)
    yield con
    con.close()

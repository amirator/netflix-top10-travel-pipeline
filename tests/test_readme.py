import importlib.util

from top10 import config


def test_readme_matches_template_rendered_from_kpis(kpis, db):
    spec = importlib.util.spec_from_file_location("build_readme", config.ROOT / "scripts" / "build_readme.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert (config.ROOT / "README.md").read_text() == mod.render(), "README drifted: run python scripts/build_readme.py"


def test_readme_states_status_and_author():
    text = (config.ROOT / "README.md").read_text()
    assert "initial prototype" in text
    assert "Mohammad Amir Khan" in text and "https://github.com/amirator" in text

import hashlib
import json

from top10 import config, extract


def test_sha256_matches_hashlib(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"netflix top 10" * 1000)
    assert extract.sha256(f) == hashlib.sha256(f.read_bytes()).hexdigest()


def test_manifest_records_url_date_and_checksum(raw_paths):
    manifest = json.loads(config.MANIFEST.read_text())
    by_name = {e["name"]: e for e in manifest["files"]}
    assert set(by_name) == {"global", "countries", "wikidata_languages"}
    for name in ("global", "countries"):
        e = by_name[name]
        assert e["source_url"] == config.SOURCES[name]
        assert e["source_url"].startswith("https://www.netflix.com/tudum/top10/data/")
        assert e["downloaded_at_utc"]
        # the checksum in the manifest is the checksum of the file on disk
        assert e["sha256"] == extract.sha256(config.ROOT / e["file"])
    assert by_name["wikidata_languages"]["sha256"] == extract.sha256(config.WIKIDATA_SNAPSHOT)


def test_wikidata_snapshot_has_expected_columns():
    header = config.WIKIDATA_SNAPSHOT.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert header == extract.WD_FIELDS

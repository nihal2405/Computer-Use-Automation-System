"""Acceptance reports must not import secrets or turn failing checks into success."""

import json

import pytest

from scripts.acceptance import SOURCE_FILES, snapshot
from scripts.acceptance import test_summary as summarize


def source_tree(path):
    path.mkdir()
    for name in SOURCE_FILES:
        (path / name).write_text("placeholder")
    return path


def test_source_snapshot_excludes_credentials_environments_and_generated_files(tmp_path):
    source = source_tree(tmp_path / "source")
    for name in (
        ".env",
        ".venv/private",
        "runs/private",
        "src/__pycache__/private.pyc",
        "src/.env.local",
    ):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("do-not-export")
    (source / "src/main.py").write_text("print('source')")
    hashes = snapshot(source, tmp_path / "copy")
    assert "src/main.py" in hashes and ".env.example" in hashes
    assert not any(
        "do-not-export" in p.read_text() for p in (tmp_path / "copy").rglob("*") if p.is_file()
    )


def test_source_snapshot_rejects_symlinks_to_outside_files(tmp_path):
    source = source_tree(tmp_path / "source")
    (source / "src").mkdir()
    private = tmp_path / "private"
    private.write_text("private")
    (source / "src/leak.py").symlink_to(private)
    with pytest.raises(ValueError, match="symlinks"):
        snapshot(source, tmp_path / "copy")


def test_test_report_preserves_failures_and_skips_without_captured_values(tmp_path):
    xml = tmp_path / "results.xml"
    xml.write_text("""<testsuites><testsuite>
      <testcase classname="tests.safety" name="test_ok"/>
      <testcase classname="tests.safety" name="test_fail[private-value]"><failure>private-trace</failure></testcase>
      <testcase classname="tests.safety" name="test_skip"><skipped/></testcase>
    </testsuite></testsuites>""")
    summary = summarize(xml)
    assert summary["passed"] == 1 and summary["failed"] == 1 and summary["skipped"] == 1
    assert "private" not in json.dumps(summary)


def test_empty_test_report_cannot_claim_passed_tests(tmp_path):
    xml = tmp_path / "results.xml"
    xml.write_text("<testsuites/>")
    assert summarize(xml)["total"] == 0

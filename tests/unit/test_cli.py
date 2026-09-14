"""The validation command must enforce the same file limits as replay."""

import json
from pathlib import Path

import pytest

from computer_use.cli import main


@pytest.mark.parametrize("case", ["duplicate_key", "oversized"])
def test_validation_rejects_files_that_replay_cannot_load(tmp_path, monkeypatch, capsys, case):
    fixture = Path(__file__).parents[1] / "fixtures/read_savings_balance.json"
    contents = fixture.read_text()
    if case == "duplicate_key":
        contents = contents.replace("{", '{"schema_version": "1.0",', 1)
    else:
        contents += " " * 1_048_577
    path = tmp_path / "invalid.json"
    path.write_text(contents)
    monkeypatch.setattr("sys.argv", ["computer-use", "validate-capability", str(path)])
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"

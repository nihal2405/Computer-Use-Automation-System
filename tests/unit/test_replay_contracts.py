"""Replay preflight and extraction require neither a browser nor model access."""

import json
from pathlib import Path

import pytest

from computer_use.capabilities.store import ArtifactError, CapabilityStore
from computer_use.replay.engine import ReplayEngine, ReplayRequestError
from computer_use.replay.recovery import RecoveryBudget, extract_value
from computer_use.schemas.capability import Capability
from computer_use.schemas.common import ValueSpec
from computer_use.settings import load_configuration

ROOT = Path(__file__).parents[2]
ARTIFACT = ROOT / "tests/fixtures/read_savings_balance.json"


@pytest.mark.parametrize("content", ["{", '{"schema_version":"1.0","schema_version":"2.0"}', '{"schema_version":"2.0"}', "[]", '"secret"', "x" * 1_048_577])
def test_artifact_loader_rejects_malformed_unsupported_and_oversized_files(tmp_path, content):
    path = tmp_path / "artifact.json"
    path.write_text(content)
    with pytest.raises(ArtifactError, match="missing, malformed, or unsupported"):
        CapabilityStore.load(path)


def test_artifact_loader_rejects_missing_file(tmp_path):
    with pytest.raises(ArtifactError):
        CapabilityStore.load(tmp_path / "missing.json")


@pytest.mark.parametrize("inputs", [{}, {"member_id": 2002}, {"member_id": "2002", "extra": "private"}, {"member_id": "../private"}, []])
def test_invalid_inputs_fail_before_browser_or_evidence_creation(tmp_path, inputs):
    with pytest.raises(ReplayRequestError):
        ReplayEngine(capability=CapabilityStore.load(ARTIFACT), configuration=load_configuration(ROOT),
                     project_root=tmp_path, inputs=inputs)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("mutation", ["route", "target", "reference", "version", "action"])
def test_invalid_or_unapproved_artifact_fails_before_execution(tmp_path, mutation):
    data = json.loads(ARTIFACT.read_text())
    if mutation == "route":
        data["steps"][0]["action"]["path"] = "/demo"
    elif mutation == "target":
        data["target"]["versions"] = ["9.0"]
    elif mutation == "reference":
        data["steps"][1]["action"]["value"]["ref"] = "inputs.undeclared"
    elif mutation == "version":
        data["schema_version"] = "2.0"
    else:
        data["steps"][2]["action"]["target"]["name"]["value"] = "Transfer money"
    with pytest.raises(ReplayRequestError):
        ReplayEngine(capability=data, configuration=load_configuration(ROOT), project_root=tmp_path, inputs={"member_id": "2002"})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(("kind", "text", "expected"), [
    ("decimal_string", "8040.20", "8040.20"), ("currency_code", "USD", "USD"),
    ("integer", "12", 12), ("boolean", "false", False), ("string", "Member", "Member"),
])
def test_strict_visible_text_conversion(kind, text, expected):
    actual = extract_value(ValueSpec(type=kind, description="Output"), text)
    assert type(actual) is type(expected) and actual == expected


@pytest.mark.parametrize(("kind", "text"), [
    ("decimal_string", "$8,040.20"), ("decimal_string", "NaN"), ("currency_code", "usd"),
    ("integer", "1.0"), ("integer", "01"), ("boolean", "yes"), ("string", ""), ("string", None),
])
def test_invalid_visible_outputs_are_not_guessed(kind, text):
    with pytest.raises(ValueError):
        extract_value(ValueSpec(type=kind, description="Output"), text)


def test_recovery_budget_is_run_wide_and_respects_runtime_limit():
    rule = CapabilityStore.load(ARTIFACT).recovery_rules[0]
    budget = RecoveryBudget(max_retries=0)
    assert budget.remaining(rule) == 1
    budget.consume(rule)
    assert budget.remaining(rule) == 0
    with pytest.raises(ValueError):
        budget.consume(rule)

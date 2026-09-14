"""Contract boundary checks; no model, browser, or live banking app is involved."""

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from computer_use.schemas import (
    Capability,
    ControlSnapshot,
    ControlTransition,
    Intervention,
    Observation,
    TargetIdentity,
    action_adapter,
    result_adapter,
    target_adapter,
)
from computer_use.schemas.common import ValueSpec

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def artifact():
    return json.loads((FIXTURES / "read_savings_balance.json").read_text())


def replace(document, path, value):
    current = document
    for part in path[:-1]:
        current = current[part]
    current[path[-1]] = value


def test_development_artifact_round_trip_and_invocation(artifact):
    capability = Capability.model_validate(artifact)
    assert capability.provenance == "development_fixture"
    assert Capability.model_validate_json(capability.model_dump_json()) == capability
    assert capability.validate_inputs({"member_id": "1001"}) == {"member_id": "1001"}
    assert capability.validate_inputs({"member_id": "2002"}) == {"member_id": "2002"}
    capability.validate_outputs({"balance": "1250.75", "currency": "USD"})
    capability.validate_target(
        TargetIdentity.model_validate_json((FIXTURES / "mock_bank_identity.json").read_text())
    )
    assert "steps" in Capability.model_json_schema()["properties"]


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("schema_version",), "2.0"),
        (("capability_version",), "1.0"),
        (("extra_field",), "unrecognized"),
        (("steps",), []),
        (("steps", 1, "id"), "open_search"),
        (("steps", 0, "action", "action"), "execute_python"),
        (("steps", 0, "action", "target"), {}),
        (("steps", 1, "action", "target", "strategy"), "coordinates"),
        (("steps", 1, "action", "target", "rationale"), "   "),
        (("steps", 1, "action", "value", "ref"), "inputs.unknown"),
        (("steps", 1, "action", "value", "ref"), "inputs.member_id.upper()"),
        (("steps", 1, "action", "value", "ref"), "outputs.balance"),
        (("steps", 3, "action", "target", "name", "ref"), "inputs.unknown"),
        (("success_checkpoint", "expected", "ref"), "inputs.unknown"),
        (("steps", 5, "action", "output"), "undeclared_balance"),
        (("steps", 6, "action", "output"), "balance"),
        (("outputs", "unused_output"), {"type": "string", "description": "Never extracted"}),
        (("outputs", "balance", "type"), "float"),
        (("inputs", "member_id", "type"), "integer"),
        (("inputs",), {}),
        (("success_checkpoint",), None),
        (("target", "versions"), []),
        (("target", "versions"), ["1.0", "1.0"]),
        (("steps", 0, "timeout_ms"), 0),
        (("steps", 0, "timeout_ms"), "1000"),
        (("steps", 0, "timeout_ms"), True),
        (("recovery_rules", 0, "max_attempts"), 4),
        (("recovery_rules", 0, "timeout_ms"), 60001),
        (("recovery_rules", 0, "strategy"), "retry_click"),
        (("provenance",), "llm_discovery"),
        (("discovery_run_id",), "fabricated_run"),
    ],
)
def test_malformed_artifacts_are_rejected(artifact, path, value):
    replace(artifact, path, value)
    with pytest.raises(ValidationError):
        Capability.model_validate(artifact)


@pytest.mark.parametrize("field", ["schema_version", "inputs", "outputs", "success_checkpoint"])
def test_required_contract_fields_cannot_be_missing(artifact, field):
    del artifact[field]
    with pytest.raises(ValidationError):
        Capability.model_validate(artifact)


@pytest.mark.parametrize(
    "path",
    [
        "https://unapproved.example/",
        "//unapproved.example/",
        "javascript:alert(1)",
        "/../admin",
        "/%2e%2e/admin",
        "/%2fexample.com",
        "/%252fexample.com",
        "/\\example.com",
        "/?token=secret",
        "/#fragment",
        "/\nadmin",
        "relative/path",
    ],
)
def test_navigation_requires_local_application_path(path):
    with pytest.raises(ValidationError):
        action_adapter.validate_python({"action": "navigate", "path": path})


@pytest.mark.parametrize(
    "inputs",
    [
        {},
        {"member_id": 123},
        {"member_id": True},
        {"member_id": ""},
        {"member_id": "1001", "extra": "x"},
        [],
    ],
)
def test_invocation_rejects_missing_extra_or_mistyped_inputs(artifact, inputs):
    with pytest.raises(ValueError):
        Capability.model_validate(artifact).validate_inputs(inputs)


@pytest.mark.parametrize(
    "outputs",
    [
        {},
        {"balance": "1.00"},
        {"balance": 1.0, "currency": "USD"},
        {"balance": "NaN", "currency": "USD"},
        {"balance": "1e3", "currency": "USD"},
        {"balance": "1,000.00", "currency": "USD"},
        {"balance": "1.00", "currency": "usd"},
        {"balance": "1.00", "currency": "USD", "member_name": "not declared"},
    ],
)
def test_invocation_rejects_invalid_outputs(artifact, outputs):
    with pytest.raises(ValueError):
        Capability.model_validate(artifact).validate_outputs(outputs)


@pytest.mark.parametrize(
    ("kind", "valid", "invalid"),
    [
        ("integer", 42, True),
        ("boolean", False, 0),
        ("string", "00123", 123),
        ("decimal_string", "-12.50", "Infinity"),
        ("currency_code", "EUR", "euro"),
    ],
)
def test_declared_types_do_not_coerce_values(kind, valid, invalid):
    spec = ValueSpec(type=kind, description="A typed parameter")
    spec.check(valid)
    with pytest.raises(ValueError):
        spec.check(invalid)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("product", "other_bank"),
        ("version", "2.0"),
        ("surface", "desktop"),
    ],
)
def test_incompatible_target_is_rejected(artifact, field, value):
    identity = {"product": "synthetic_bank", "version": "1.0", "surface": "browser"}
    identity[field] = value
    with pytest.raises(ValueError):
        Capability.model_validate(artifact).validate_target(TargetIdentity(**identity))


def test_references_in_nested_conditions_are_checked(artifact):
    reference_target = deepcopy(artifact["steps"][3]["action"]["target"])
    reference_target["name"]["ref"] = "inputs.unknown"
    for field in ("precondition", "postcondition"):
        changed = deepcopy(artifact)
        changed["steps"][0][field] = {"kind": "visible", "target": reference_target}
        with pytest.raises(ValidationError):
            Capability.model_validate(changed)
    for rules, condition_field in (("business_outcomes", "when"), ("recovery_rules", "until")):
        changed = deepcopy(artifact)
        changed[rules][0][condition_field] = {"kind": "visible", "target": reference_target}
        with pytest.raises(ValidationError):
            Capability.model_validate(changed)


def test_duplicate_and_conflicting_rule_codes_rejected(artifact):
    for field in ("business_outcomes", "recovery_rules"):
        changed = deepcopy(artifact)
        changed[field].append(deepcopy(changed[field][0]))
        with pytest.raises(ValidationError):
            Capability.model_validate(changed)
    artifact["business_outcomes"][0]["code"] = "slow_loading"
    with pytest.raises(ValidationError):
        Capability.model_validate(artifact)


def test_actions_and_targets_round_trip(artifact):
    actions = [step["action"] for step in artifact["steps"]]
    condition = artifact["success_checkpoint"]
    actions += [
        {"action": "wait", "condition": condition, "timeout_ms": 1000},
        {"action": "verify", "condition": condition},
    ]
    for value in actions:
        model = action_adapter.validate_python(value)
        assert action_adapter.validate_json(model.model_dump_json()) == model
    text_target = artifact["business_outcomes"][0]["when"]["target"]
    assert target_adapter.validate_python(text_target).strategy == "text"


@pytest.fixture
def run_context():
    return {
        "schema_version": "1.0",
        "run_id": "run_1",
        "session_id": "session_1",
        "mode": "replay",
        "capability_id": "read_savings_balance",
        "capability_version": "1.0.0",
    }


def test_results_are_distinct_and_bound_to_capability(artifact, run_context):
    capability = Capability.model_validate(artifact)
    results = [
        {
            **run_context,
            "status": "success",
            "checkpoint_verified": True,
            "outputs": {"balance": "1250.75", "currency": "USD"},
        },
        {
            **run_context,
            "status": "business_outcome",
            "code": "member_not_found",
            "step_id": "submit_search",
            "summary": "No matching member",
        },
        {
            **run_context,
            "status": "failure",
            "code": "permission_denied",
            "diagnostic": {
                "step_id": "open_accounts",
                "expected": "Accounts visible",
                "observed": "Permission denied",
                "evidence_ref": "sanitized_snapshot_1",
            },
        },
    ]
    for value in results:
        result = capability.validate_result(value)
        assert result_adapter.validate_json(result.model_dump_json()) == result
    for value in (False, 1, "true"):
        changed = deepcopy(results[0])
        changed["checkpoint_verified"] = value
        with pytest.raises(ValueError):
            capability.validate_result(changed)
    for path, value in [
        (("outputs", "extra"), "bad"),
        (("outputs", "balance"), "NaN"),
        (("capability_id",), "another_flow"),
        (("capability_version",), "2.0.0"),
    ]:
        changed = deepcopy(results[0])
        replace(changed, path, value)
        with pytest.raises(ValueError):
            capability.validate_result(changed)
    for original in results[1:]:
        changed = deepcopy(original)
        changed["outputs"] = {"balance": "1.00"}
        with pytest.raises(ValueError):
            capability.validate_result(changed)
    results[1]["code"] = "unknown_business_outcome"
    with pytest.raises(ValueError):
        capability.validate_result(results[1])
    results[2]["diagnostic"]["step_id"] = "nonexistent_step"
    with pytest.raises(ValueError):
        capability.validate_result(results[2])


def test_discovery_can_fail_before_a_capability_exists():
    failure = {
        "schema_version": "1.0",
        "run_id": "run_1",
        "session_id": "session_1",
        "mode": "discovery",
        "status": "failure",
        "code": "timeout",
        "diagnostic": {"step_id": None, "expected": "Initial page ready", "observed": "Loading"},
    }
    assert result_adapter.validate_python(failure).capability_id is None
    failure["mode"] = "replay"
    with pytest.raises(ValidationError):
        result_adapter.validate_python(failure)


@pytest.fixture
def observation():
    return {
        "schema_version": "1.0",
        "run_id": "run_1",
        "session_id": "session_1",
        "sequence": 3,
        "target": {"product": "synthetic_bank", "version": "1.0", "surface": "browser"},
        "location": "/members",
        "summary": "A confirmation dialog blocks navigation",
        "state": "unexpected_dialog",
        "controls": [],
        "evidence_ref": "sanitized_snapshot_1",
    }


def test_observation_rejects_duplicate_ids_unbound_targets_and_objects(observation, artifact):
    control = {
        "id": "search",
        "target": artifact["steps"][2]["action"]["target"],
        "visible": True,
        "enabled": True,
    }
    observation["controls"] = [control]
    model = Observation.model_validate(observation)
    assert Observation.model_validate_json(model.model_dump_json()) == model
    observation["controls"].append(control)
    with pytest.raises(ValidationError):
        Observation.model_validate(observation)
    observation["controls"] = [{**control, "target": artifact["steps"][3]["action"]["target"]}]
    with pytest.raises(ValidationError):
        Observation.model_validate(observation)
    observation["controls"] = [object()]
    with pytest.raises(ValidationError):
        Observation.model_validate(observation)


@pytest.fixture
def intervention(observation):
    return {
        "schema_version": "1.0",
        "id": "intervention_1",
        "run_id": "run_1",
        "session_id": "session_1",
        "goal": "Read a synthetic savings balance",
        "capability_id": "read_savings_balance",
        "capability_version": "1.0.0",
        "step_id": "open_accounts",
        "reason": "unknown_state",
        "context": observation,
        "diagnostic": {
            "step_id": "open_accounts",
            "expected": "Accounts visible",
            "observed": "Unexpected confirmation dialog",
        },
        "control": {"session_id": "session_1", "state": "AWAITING_HUMAN", "owner": "none"},
    }


def test_intervention_open_and_resolved_round_trip(intervention):
    model = Intervention.model_validate(intervention)
    assert Intervention.model_validate_json(model.model_dump_json()) == model
    intervention["resolution"] = {
        "action": "resume",
        "operator_id": "operator_1",
        "summary": "Dismissed dialog",
        "human_actions_ref": "sanitized_human_events_1",
        "state_verified": True,
        "verification": intervention["diagnostic"],
        "resume_step_id": "open_accounts",
    }
    intervention["control"].update(state="AUTOMATION_RUNNING", owner="automation")
    Intervention.model_validate(intervention)
    intervention["resolution"]["state_verified"] = False
    with pytest.raises(ValidationError):
        Intervention.model_validate(intervention)


@pytest.mark.parametrize(
    ("action", "state", "verified"),
    [
        ("complete", "COMPLETED", True),
        ("abort", "FAILED", False),
    ],
)
def test_intervention_can_complete_or_abort(intervention, action, state, verified):
    intervention["control"].update(state=state, owner="none")
    intervention["resolution"] = {
        "action": action,
        "operator_id": "operator_1",
        "summary": "Resolved intervention",
        "human_actions_ref": "sanitized_human_events_1",
        "state_verified": verified,
        "verification": intervention["diagnostic"] if verified else None,
    }
    Intervention.model_validate(intervention)
    intervention["resolution"]["resume_step_id"] = "open_accounts"
    with pytest.raises(ValidationError):
        Intervention.model_validate(intervention)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("context", "run_id"), "another_run"),
        (("context", "session_id"), "another_session"),
        (("control", "session_id"), "another_session"),
        (("control", "owner"), "automation"),
        (("diagnostic", "step_id"), "another_step"),
        (("capability_version",), None),
        (("control", "state"), "COMPLETED"),
    ],
)
def test_inconsistent_intervention_rejected(intervention, path, value):
    replace(intervention, path, value)
    with pytest.raises(ValidationError):
        Intervention.model_validate(intervention)


def test_control_transfer_requires_same_session_and_resume_check():
    states = [
        ("AUTOMATION_RUNNING", "automation"),
        ("AWAITING_HUMAN", "none"),
        ("HUMAN_CONTROL", "human"),
        ("RESUME_CHECK", "automation"),
        ("COMPLETED", "none"),
    ]
    snapshots = [ControlSnapshot(session_id="session_1", state=s, owner=o) for s, o in states]
    for before, after in zip(snapshots, snapshots[1:]):
        ControlTransition(before=before, after=after, reason="Verified handoff transition")
    assert [snapshot.automation_actions_allowed for snapshot in snapshots] == [
        True,
        False,
        False,
        False,
        False,
    ]
    for before, after in [
        (snapshots[2], snapshots[0]),
        (snapshots[4], snapshots[0]),
        (snapshots[1], snapshots[0]),
    ]:
        with pytest.raises(ValidationError):
            ControlTransition(before=before, after=after, reason="Invalid transition")
    with pytest.raises(ValidationError):
        ControlTransition(
            before=snapshots[0],
            after=ControlSnapshot(
                session_id="another_session", state="AWAITING_HUMAN", owner="none"
            ),
            reason="Must retain the browser",
        )


def test_mutated_models_are_rechecked_at_validation_boundary(artifact):
    model = Capability.model_validate(artifact)
    model.steps.append(model.steps[0])
    with pytest.raises(ValidationError):
        Capability.model_validate(model)


def test_control_snapshot_cannot_change_owner_in_place():
    snapshot = ControlSnapshot(session_id="session_1", state="HUMAN_CONTROL", owner="human")
    with pytest.raises(ValidationError):
        snapshot.owner = "automation"
    assert snapshot.owner == "human"
    assert not snapshot.automation_actions_allowed


def test_cli_validates_fixture_without_execution_and_hides_bad_values(tmp_path):
    command = [
        sys.executable,
        "-m",
        "computer_use",
        "validate-capability",
        str(FIXTURES / "read_savings_balance.json"),
    ]
    completed = subprocess.run(
        command
        + [
            "--inputs",
            '{"member_id":"1001"}',
            "--target",
            str(FIXTURES / "mock_bank_identity.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["executed"] is False
    assert json.loads(completed.stdout)["target_checked"] is True
    secret = "TEST_SECRET_MUST_NOT_BE_PRINTED"
    bad = tmp_path / "invalid.json"
    bad.write_text(json.dumps({"schema_version": secret}))
    completed = subprocess.run(
        command[:4] + [str(bad)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "invalid"
    assert secret not in completed.stdout + completed.stderr


@pytest.mark.parametrize(
    "inputs",
    [
        "null",
        "[]",
        "invalid json",
        '{"member_id":123}',
        '{"member_id":"1001","secret":"SHOULD_NOT_PRINT"}',
    ],
)
def test_cli_rejects_malformed_invocations_without_tracebacks(inputs):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "computer_use",
            "validate-capability",
            str(FIXTURES / "read_savings_balance.json"),
            "--inputs",
            inputs,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["status"] == "invalid"
    assert "SHOULD_NOT_PRINT" not in completed.stdout
    assert completed.stderr == ""

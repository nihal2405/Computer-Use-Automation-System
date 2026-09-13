"""Configuration rejection and fail-closed redaction without any browser."""

import json
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from computer_use.observability.evidence import EvidenceStore
from computer_use.safety.policy import Policy
from computer_use.safety.redaction import Redactor
from computer_use.safety.urls import split_url
from computer_use.settings import ConfigurationError, load_configuration
from computer_use.capabilities.store import CapabilityStore
from computer_use.schemas.capability import Capability
from computer_use.observability.evidence import PersistenceError

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("change", [
    ("settings.yaml", "max_steps", "30"),
    ("settings.yaml", "unexpected", True),
    ("settings.yaml", "run_directory", "../../escape"),
    ("policy.yaml", "default_decision", "allow"),
    ("policy.yaml", "risky_action_decision", "allow"),
    ("policy.yaml", "allowed_origins", []),
    ("targets/mock_bank.yaml", "entry_url", "https://unapproved.example/"),
    ("targets/mock_bank.yaml", "locator_overrides", {"button": "unreviewed"}),
])
def test_invalid_configuration_is_rejected_without_content_leak(tmp_path, change):
    for name in ("settings.yaml", "policy.yaml", "targets/mock_bank.yaml"):
        path = tmp_path / "config" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = yaml.safe_load((ROOT / "config" / name).read_text())
        if name == change[0]:
            data[change[1]] = change[2]
        path.write_text(yaml.safe_dump(data))
    with pytest.raises(ConfigurationError) as error:
        load_configuration(tmp_path)
    assert "unapproved.example" not in str(error.value)


def test_duplicate_yaml_keys_are_not_silently_overwritten(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/settings.yaml").write_text("max_steps: 30\nmax_steps: 99\n")
    with pytest.raises(ConfigurationError):
        load_configuration(tmp_path)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/%252e%252e/transfer", "http://127.0.0.1:8000/../transfer",
    "http://user:password@127.0.0.1:8000/", "javascript:alert(1)",
    "http://127.0.0.1:8000/ members", "http://127.0.0.1:8000//members",
    "http://127.0.0.1:8000/members?token=secret", "http://127.0.0.1:8000/\\evil",
])
def test_noncanonical_urls_fail_closed(url):
    with pytest.raises(ValueError):
        split_url(url)


def test_redaction_covers_unknown_text_keys_numbers_and_trusted_secret_collisions(tmp_path):
    redactor = Redactor(["Search", "Member ID"])
    redactor.register(["Search"])
    store = EvidenceStore(tmp_path, redactor, run_id=str(uuid4()), session_id=str(uuid4()), mode="replay")
    for kind in ("error", "human_event", "artifact_diagnostic", "model_explanation", "dom_structure"):
        store.diagnostic(kind, {"unknown-sensitive-key": ["Unknown Person", "x@example.com", "Search", 123456789, {"text": "Member ID"}]})
    text = "".join(path.read_text() for path in store.directory.iterdir())
    assert "Member ID" in text
    assert all(value not in text for value in ("unknown-sensitive-key", "Unknown Person", "x@example.com", "Search", "123456789"))
    assert redactor.token("private") != Redactor().token("private")
    assert "1001" not in redactor.token("1001")


@pytest.mark.parametrize("values", [{}, {"member_id": 1001}, {"member_id": "abc"}, {"member_id": "1001", "secret": "no"}])
def test_policy_rejects_invalid_invocation_inputs(values):
    with pytest.raises(Exception, match="invalid_input"):
        Policy(load_configuration(ROOT).policy).inputs(values)


def test_artifact_export_preserves_valid_workflow_without_sensitive_prose(tmp_path):
    configuration = load_configuration(ROOT)
    redactor = Redactor(Policy(configuration.policy).vocabulary() | {configuration.target.product})
    store = CapabilityStore(tmp_path, redactor)
    data = json.loads((ROOT / "tests/fixtures/read_savings_balance.json").read_text())
    data["description"] = "Private Person private@example.com"
    data["steps"][1]["action"]["target"]["rationale"] = "token-super-secret"
    path = store.save(data)
    text = path.read_text()
    assert all(v not in text for v in ("Private Person", "private@example.com", "token-super-secret"))
    saved = Capability.model_validate_json(text)
    assert set(saved.inputs) == {"member_id"} and set(saved.outputs) == {"balance", "currency"}
    assert saved.steps[1].action.value.ref == "inputs.member_id"
    before = list(tmp_path.iterdir())
    data["steps"][3]["action"]["target"]["name"] = {"source": "literal", "value": "secret-member-identifier"}
    with pytest.raises(PersistenceError):
        store.save(data)
    assert list(tmp_path.iterdir()) == before

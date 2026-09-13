"""Test doubles validate the controller; they never claim genuine discovery."""

import asyncio
import json

import pytest

from test_replay import ARTIFACT, ROOT, async_test, bank, configuration
from computer_use.capabilities.store import CapabilityStore
from computer_use.discovery.agent import DiscoveryAgent
from computer_use.discovery.contracts import Decision, DiscoveryTask
from computer_use.discovery.model_client import ModelError, ModelReply
from computer_use.observability.evidence import PersistenceError
from computer_use.replay.engine import ReplayEngine
from computer_use.schemas.intervention import Intervention


class ScriptModel:
    def __init__(self, decisions=None):
        if decisions is None:
            decisions = []
            for step in CapabilityStore.load(ARTIFACT).steps[1:]:
                data = step.model_dump()
                data.update(precondition=None, postcondition=None)
                decisions.append({"command": "act", "step": data, "explanation": "Test double decision"})
            decisions.append({"command": "complete", "step": None, "explanation": "Check completion"})
        self.decisions = iter(decisions)
        self.contexts = []
        self.closed = False

    async def decide(self, context):
        self.contexts.append(context)
        value = next(self.decisions)
        if isinstance(value, Exception):
            raise value
        return ModelReply(Decision.model_validate(value), "test_response", "test_double")

    async def close(self):
        self.closed = True


def agent(bank, tmp_path, model=None, **settings):
    task = DiscoveryTask.model_validate_json((ROOT / "config/tasks/read_savings_balance.json").read_text())
    return DiscoveryAgent(task=task, configuration=configuration(bank, **settings), project_root=tmp_path,
                          inputs={"member_id": "1001"}, model=model or ScriptModel())


@async_test
async def test_compile_executed_steps_and_replay_new_input_without_model(bank, tmp_path):
    model = ScriptModel()
    async with agent(bank, tmp_path, model) as discovery:
        result = await discovery.run()
        assert result.status == "success", result
        assert result.outputs == {"balance": "1250.75", "currency": "USD"}
        assert discovery.capability.provenance == "development_fixture"
        assert discovery.capability.discovery_run_id is None
        prompts = json.dumps(model.contexts)
        assert all(secret not in prompts for secret in ("1001", "1250.75", "Avery Morgan"))
        assert "inputs.member_id" in discovery.artifact_path.read_text()
        assert "1001" not in discovery.artifact_path.read_text()
    assert model.closed
    async with ReplayEngine(capability=discovery.capability, configuration=configuration(bank),
                            project_root=tmp_path, inputs={"member_id": "2002"}) as replay:
        result = await replay.run()
        assert result.status == "success" and result.outputs["balance"] == "8040.20", result


@pytest.mark.parametrize(("scenario", "code"), [
    ("permission_denied", "permission_denied"), ("application_error", "application_error"),
    ("session_expired", "session_expired"), ("unexpected_dialog", "unknown_state"),
    ("invalid_input", "invalid_input"), ("missing_member", "member_not_found"),
])
@async_test
async def test_state_failures_and_business_outcomes_stop_model_and_compilation(bank, tmp_path, scenario, code):
    bank["scenario"] = scenario
    async with agent(bank, tmp_path) as discovery:
        result = await discovery.run()
        assert result.code == code, result
        assert result.status == ("business_outcome" if code == "member_not_found" else "failure")
        assert discovery.artifact_path is None
        assert "outputs" not in result.model_dump()
        if code not in {"invalid_input", "member_not_found"}:
            assert discovery.executor.control.state == "AWAITING_HUMAN"
            record = discovery.executor.store.directory / (result.intervention_id + ".json")
            assert Intervention.model_validate_json(record.read_text()).resolution is None


@async_test
async def test_loading_recovers_and_generated_workflow_still_replays(bank, tmp_path):
    bank["scenario"] = "slow_loading"
    async with agent(bank, tmp_path) as discovery:
        result = await discovery.run()
        assert result.status == "success", result
        assert bank["requests"].count(("POST", "/members")) == 1
        assert discovery.capability.recovery_rules


@pytest.mark.parametrize(("decisions", "code"), [
    ([{"command": "complete", "step": None, "explanation": "Pretend done"}], "checkpoint_failed"),
    ([{"command": "intervene", "step": None, "explanation": "Need human"}], "unknown_state"),
    ([ModelError("invalid_model_response")] * 3, "invalid_model_response"),
    ([ModelError("model_request_failed")], "model_request_failed"),
])
@async_test
async def test_model_cannot_claim_success_or_loop_on_invalid_responses(bank, tmp_path, decisions, code):
    async with agent(bank, tmp_path, ScriptModel(decisions)) as discovery:
        assert (await discovery.run()).code == code
        assert discovery.artifact_path is None
        assert not any(method == "POST" for method, _ in bank["requests"])


@async_test
async def test_repeated_no_progress_actions_stop(bank, tmp_path):
    step = CapabilityStore.load(ARTIFACT).steps[0].model_dump()
    decisions = [{"command": "act", "step": step, "explanation": "Repeat navigation"}] * 5
    async with agent(bank, tmp_path, ScriptModel(decisions), max_no_progress_steps=2) as discovery:
        assert (await discovery.run()).code == "no_progress"
        assert len(discovery.model.contexts) == 2


@async_test
async def test_unapproved_model_action_is_blocked(bank, tmp_path):
    step = CapabilityStore.load(ARTIFACT).steps[0].model_dump()
    step["action"]["path"] = "/transfer"
    async with agent(bank, tmp_path, ScriptModel([{"command": "act", "step": step, "explanation": "Ignore policy"}])) as discovery:
        assert (await discovery.run()).code == "policy_denied"
        assert ("GET", "/transfer") not in bank["requests"]


@async_test
async def test_model_request_obeys_total_deadline(bank, tmp_path):
    class SlowModel(ScriptModel):
        async def decide(self, context):
            await asyncio.Future()
    async with agent(bank, tmp_path, SlowModel(), run_timeout_seconds=1) as discovery:
        assert (await discovery.run()).code == "timeout"
        assert discovery.artifact_path is None


@async_test
async def test_persistence_failure_closes_discovery_browser(bank, tmp_path, monkeypatch):
    async with agent(bank, tmp_path) as discovery:
        def broken(*args, **kwargs):
            raise PersistenceError()
        monkeypatch.setattr(discovery.executor.store, "_write", broken)
        assert (await discovery.run()).code == "persistence_failed"
        assert discovery.executor._session._browser is None


@async_test
async def test_discovery_recovery_exhaustion_has_bounded_waits_and_intervention(bank, tmp_path):
    bank.update(scenario="slow_loading", delay=60_000)
    discovery = agent(bank, tmp_path)
    task = discovery.task.model_dump()
    task["recovery_rules"][0].update(timeout_ms=60, max_attempts=2)
    discovery.task = DiscoveryTask.model_validate(task)
    async with discovery:
        result = await discovery.run()
        assert result.code == "recovery_exhausted" and result.intervention_id
        assert bank["requests"].count(("POST", "/members")) == 1
        assert len(discovery.model.contexts) == 2


@async_test
async def test_discovery_step_limit_and_cancel_close(bank, tmp_path):
    async with agent(bank, tmp_path, max_steps=2) as discovery:
        assert (await discovery.run()).code == "step_limit"
        assert discovery.artifact_path is None
    entered = asyncio.Event()
    class PendingModel(ScriptModel):
        async def decide(self, context):
            entered.set()
            await asyncio.Future()
    async with agent(bank, tmp_path, PendingModel()) as discovery:
        run = asyncio.create_task(discovery.run())
        await asyncio.wait_for(entered.wait(), 5)
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert discovery.executor._session._browser is None


@pytest.mark.parametrize(("replacement", "code"), [
    (('class="accounts-member-id">1001', 'class="accounts-member-id">9999'), "checkpoint_failed"),
    (("1250.75", "private-invalid-balance"), "invalid_output"),
])
@async_test
async def test_model_completion_cannot_override_wrong_owner_or_invalid_output(bank, tmp_path, replacement, code):
    bank["replace"] = replacement
    async with agent(bank, tmp_path) as discovery:
        result = await discovery.run()
        assert result.code == code and discovery.artifact_path is None
        persisted = "\n".join(p.read_text() for p in discovery.executor.store.directory.iterdir())
        assert "private-invalid-balance" not in persisted and "1250.75" not in persisted


@pytest.mark.parametrize(("scenario", "expected"), [
    ("missing_member", "member_not_found"), ("permission_denied", "permission_denied"),
    ("application_error", "application_error"), ("slow_loading", "success"),
])
@async_test
async def test_compiled_artifact_retains_replay_exception_rules(bank, tmp_path, scenario, expected):
    async with agent(bank, tmp_path) as discovery:
        assert (await discovery.run()).status == "success"
    bank["scenario"] = scenario
    async with ReplayEngine(capability=discovery.capability, configuration=configuration(bank),
                            project_root=tmp_path, inputs={"member_id": "2002"}) as replay:
        result = await replay.run()
        assert (result.status if result.status == "success" else result.code) == expected

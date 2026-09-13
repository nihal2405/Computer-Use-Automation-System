"""Replay the development artifact against real Chromium and synthetic bank pages."""

import asyncio
from functools import wraps
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

from flask import request
import pytest
from werkzeug.serving import make_server
import yaml

from computer_use.capabilities.store import CapabilityStore
from computer_use.observability.evidence import PersistenceError
from computer_use.replay.engine import ReplayEngine
from computer_use.schemas.capability import Capability
from computer_use.schemas.intervention import Intervention
from computer_use.settings import Configuration, load_configuration
from computer_use.surfaces.base import SurfaceError
from mock_app.app import create_app

ROOT = Path(__file__).parents[2]
ARTIFACT = Path(os.environ.get("REPLAY_TEST_ARTIFACT", str(ROOT / "tests/fixtures/read_savings_balance.json")))


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


@pytest.fixture
def bank():
    state = {"scenario": "normal", "requests": [], "replace": None, "delay": 1500}
    app = create_app({"TESTING": True})

    @app.before_request
    def record():
        app.config.update(DEFAULT_SCENARIO=state["scenario"], SLOW_LOAD_MS=state["delay"])
        state["requests"].append((request.method, request.path))

    # Configure the scenario before the app initializes this browser's session.
    app.before_request_funcs[None].insert(0, app.before_request_funcs[None].pop())

    @app.after_request
    def change_page(response):
        if state["replace"] and request.path.endswith("/accounts"):
            old, new = state["replace"]
            response.set_data(response.get_data(as_text=True).replace(old, new))
        return response

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def configuration(bank, **settings):
    data = load_configuration(ROOT).model_dump()
    data["target"]["entry_url"] = bank["url"] + "/"
    data["policy"]["allowed_origins"] = [bank["url"]]
    data["runtime"]["browser"]["headless"] = True
    data["runtime"].update(settings)
    return Configuration.model_validate(data)


def engine(bank, tmp_path, member="2002", capability=None, **settings):
    return ReplayEngine(capability=capability or CapabilityStore.load(ARTIFACT),
        configuration=configuration(bank, **settings), project_root=tmp_path, inputs={"member_id": member})


def events(replay):
    return [json.loads(line) for line in (replay.executor.store.directory / "events.jsonl").read_text().splitlines()]


def persisted(replay):
    return "\n".join(path.read_text() for path in replay.executor.store.directory.iterdir())


@pytest.mark.parametrize(("member", "balance"), [("1001", "1250.75"), ("2002", "8040.20")])
@async_test
async def test_same_artifact_binds_new_inputs_and_validates_visible_outputs(bank, tmp_path, member, balance):
    original = ARTIFACT.read_bytes()
    async with engine(bank, tmp_path, member) as replay:
        result = await replay.run()
        assert result.status == "success", result
        assert result.outputs == {"balance": balance, "currency": "USD"}
        assert result.mode == "replay" and result.checkpoint_verified
        assert replay.executor.control.state == "COMPLETED"
        assert ("GET", f"/members/{member}/accounts") in bank["requests"]
        assert events(replay)[-1]["event"] == "run_completed"
        assert all(secret not in persisted(replay) for secret in (member, balance, "Jordan Ellis", "Avery Morgan"))
        with pytest.raises(RuntimeError, match="only once"):
            await replay.run()
    assert ARTIFACT.read_bytes() == original


@pytest.mark.parametrize(("scenario", "member"), [("missing_member", "2002"), ("normal", "9999")])
@async_test
async def test_not_found_is_a_business_outcome_without_balance(bank, tmp_path, scenario, member):
    bank["scenario"] = scenario
    async with engine(bank, tmp_path, member) as replay:
        result = await replay.run()
        assert result.status == "business_outcome" and result.code == "member_not_found", result
        assert "outputs" not in result.model_dump() and replay.intervention is None
        assert not any(path.endswith("/accounts") for _, path in bank["requests"])


@async_test
async def test_loading_recovers_without_resubmitting_search(bank, tmp_path):
    bank["scenario"] = "slow_loading"
    async with engine(bank, tmp_path) as replay:
        result = await replay.run()
        assert result.status == "success", result
        assert result.outputs["balance"] == "8040.20"
        assert bank["requests"].count(("POST", "/members")) == 1
        assert any(event["event"] == "recovery_started" for event in events(replay))


@async_test
async def test_exhaustion_emits_valid_sanitized_intervention_and_retains_session(bank, tmp_path):
    bank.update(scenario="slow_loading", delay=60_000)
    data = CapabilityStore.load(ARTIFACT).model_dump()
    data["recovery_rules"][0].update(timeout_ms=80, max_attempts=2)
    async with engine(bank, tmp_path, capability=Capability.model_validate(data)) as replay:
        result = await replay.run()
        assert result.status == "failure" and result.code == "recovery_exhausted", result
        assert result.intervention_id and "outputs" not in result.model_dump()
        path = replay.executor.store.directory / (result.intervention_id + ".json")
        record = Intervention.model_validate_json(path.read_text())
        assert record.reason == "recovery_exhausted" and record.resolution is None
        assert record.control.state == "AWAITING_HUMAN"
        assert record.run_id == result.run_id and record.session_id == result.session_id
        assert not replay.executor._session._page.is_closed()
        assert (await replay.executor.execute_step(replay.capability.steps[2])).code == "ownership_denied"
        assert bank["requests"].count(("POST", "/members")) == 1
        assert len([event for event in events(replay) if event["event"] == "recovery_started"]) == 2
        assert "2002" not in persisted(replay)
    assert replay.executor._session._browser is None


@pytest.mark.parametrize(("scenario", "code"), [
    ("permission_denied", "permission_denied"), ("session_expired", "session_expired"),
    ("application_error", "application_error"), ("unexpected_dialog", "unknown_state"),
    ("invalid_input", "invalid_input"),
])
@async_test
async def test_application_states_do_not_become_success(bank, tmp_path, scenario, code):
    bank["scenario"] = scenario
    async with engine(bank, tmp_path) as replay:
        result = await replay.run()
        assert result.status == "failure" and result.code == code, result
        assert "outputs" not in result.model_dump()
        # A gate failure can name the upcoming read in its diagnostic. No read
        # may actually start or complete after the error state is observed.
        assert not any(e["action"] == "read" and e["event"] in {"started", "completed"} for e in events(replay))
        assert bool(result.intervention_id) == (code != "invalid_input")


@pytest.mark.parametrize(("replacement", "code"), [
    (('class="accounts-member-id">2002', 'class="accounts-member-id">9999'), "checkpoint_failed"),
    (("8040.20", "private-invalid-balance"), "invalid_output"),
    (('data-state="ready"', 'data-state="unrecognized"'), "unknown_state"),
    (('data-version="1.0"', 'data-version="9.0"'), "incompatible_target"),
])
@async_test
async def test_wrong_owner_invalid_output_unknown_state_and_version(bank, tmp_path, replacement, code):
    bank["replace"] = replacement
    async with engine(bank, tmp_path) as replay:
        result = await replay.run()
        assert result.status == "failure" and result.code == code, result
        assert "outputs" not in result.model_dump() and result.intervention_id
        assert "private-invalid-balance" not in persisted(replay)


@async_test
async def test_configured_step_and_run_limits_stop_replay(bank, tmp_path):
    async with engine(bank, tmp_path, max_steps=3) as replay:
        assert (await replay.run()).code == "step_limit"
        assert bank["requests"].count(("POST", "/members")) == 1
    async with engine(bank, tmp_path) as replay:
        replay.executor._started_at -= 121
        result = await replay.run()
        assert result.code == "timeout" and result.intervention_id


@async_test
async def test_persistence_failure_returns_failure_and_closes_browser(bank, tmp_path, monkeypatch):
    async with engine(bank, tmp_path) as replay:
        def broken(*args, **kwargs):
            raise PersistenceError()
        monkeypatch.setattr(replay.executor.store, "_write", broken)
        result = await replay.run()
        assert result.code == "persistence_failed" and "outputs" not in result.model_dump()
        assert replay.executor._session._browser is None and bank["requests"] == []


@async_test
async def test_sanitized_export_is_still_executable(bank, tmp_path):
    replay = engine(bank, tmp_path)
    saved = replay.executor.artifacts.save(replay.capability)
    async with engine(bank, tmp_path, capability=CapabilityStore.load(saved)) as second:
        result = await second.run()
        assert result.status == "success" and result.outputs["balance"] == "8040.20", result


@async_test
async def test_persistence_failure_while_reporting_surface_error_is_fail_closed(bank, tmp_path, monkeypatch):
    async with engine(bank, tmp_path) as replay:
        async def broken_observation():
            raise SurfaceError("unknown_state", "Known state", "Unknown UI state")
        async def broken_reporting(*args):
            raise PersistenceError()
        monkeypatch.setattr(replay.executor, "inspect_runtime", broken_observation)
        monkeypatch.setattr(replay.executor, "report_failure", broken_reporting)
        assert (await replay.run()).code == "persistence_failed"
        assert replay.executor._session._browser is None


@async_test
async def test_cancelling_replay_closes_its_browser(bank, tmp_path, monkeypatch):
    async with engine(bank, tmp_path) as replay:
        entered = asyncio.Event()
        async def pending(*args, **kwargs):
            entered.set()
            await asyncio.Future()
        monkeypatch.setattr(replay.executor, "execute_step", pending)
        task = asyncio.create_task(replay.run())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert replay.executor._session._browser is None


def test_cli_runs_in_separate_process_with_model_imports_blocked(bank, tmp_path):
    config = configuration(bank)
    (tmp_path / "config/targets").mkdir(parents=True)
    for path, value in [("settings.yaml", config.runtime), ("policy.yaml", config.policy), ("targets/mock_bank.yaml", config.target)]:
        (tmp_path / "config" / path).write_text(yaml.safe_dump(value.model_dump(mode="json")))
    script = '''
import importlib.abc, os, sys
class NoModel(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'litellm'} or fullname.startswith('computer_use.discovery'):
            raise AssertionError('Replay attempted a model/discovery import')
sys.meta_path.insert(0, NoModel())
for name in list(os.environ):
    if name.endswith('_API_KEY'):
        del os.environ[name]
from computer_use.cli import main
sys.exit(main())
'''
    command = [sys.executable, "-c", script, "replay", str(ARTIFACT), "--project", str(tmp_path), "--inputs", '{"member_id":"2002"}', "--headless"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=45)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["model_used"] is False and payload["session_retained"] is False
    assert payload["provenance"] == CapabilityStore.load(ARTIFACT).provenance
    assert payload["result"]["outputs"] == {"balance": "8040.20", "currency": "USD"}

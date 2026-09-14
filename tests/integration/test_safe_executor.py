"""Real-browser negative tests prove forbidden requests never reach the target."""

import asyncio
import json
from functools import wraps
from pathlib import Path
from threading import Thread

import pytest
from flask import make_response, redirect, request
from werkzeug.serving import make_server

from computer_use.execution.executor import Executor
from computer_use.observability.evidence import PersistenceError
from computer_use.schemas.capability import Capability
from computer_use.settings import Configuration, load_configuration
from computer_use.surfaces.base import SurfaceError
from mock_app.app import create_app

ROOT = Path(__file__).parents[2]
CAPABILITY = Capability.model_validate_json(
    (ROOT / "tests/fixtures/read_savings_balance.json").read_text()
)


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


@pytest.fixture
def bank():
    state = {"requests": [], "redirect": None, "second_redirect": None, "download": False}
    app = create_app({"TESTING": True, "SLOW_LOAD_MS": 300})

    @app.before_request
    def inspect_request():
        state["requests"].append((request.method, request.path))
        if state["second_redirect"] and request.path == "/members/1001":
            return redirect(state["second_redirect"])
        if state["download"] and request.path == "/":
            response = make_response("secret-file-contents")
            response.headers["Content-Disposition"] = 'attachment; filename="private.txt"'
            return response
        if state["redirect"] and request.path == "/":
            return redirect(state["redirect"])

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def config(bank, **settings):
    data = load_configuration(ROOT).model_dump()
    data["target"]["entry_url"] = bank["url"] + "/"
    data["policy"]["allowed_origins"] = [bank["url"]]
    data["runtime"]["browser"]["headless"] = True
    data["runtime"].update(settings)
    return Configuration.model_validate(data)


def executor(bank, tmp_path, *, member="1001", mode="replay", **settings):
    return Executor(
        configuration=config(bank, **settings),
        project_root=tmp_path,
        mode=mode,
        inputs={"member_id": member},
    )


def events(executor):
    return [
        json.loads(line)
        for line in (executor.store.directory / "events.jsonl").read_text().splitlines()
    ]


def all_evidence(executor):
    return "\n".join(p.read_text() for p in executor.store.directory.iterdir())


@pytest.mark.parametrize("mode", ["discovery", "replay"])
@pytest.mark.parametrize(("member", "balance"), [("1001", "1250.75"), ("2002", "8040.20")])
@async_test
async def test_shared_path_reads_balances_and_redacts_every_persistence_path(
    bank, tmp_path, mode, member, balance
):
    async with executor(bank, tmp_path, member=member, mode=mode) as engine:
        outputs = {}
        for step in CAPABILITY.steps:
            outcome = await engine.execute_step(
                step,
                model_explanation="Secret name Jane Doe, jane@example.com, token sk-do-not-store",
            )
            assert outcome.status == "success", outcome
            if step.action.action == "read":
                outputs[step.action.output] = outcome.output
        assert outputs == {"balance": balance, "currency": "USD"}
        checkpoint = await engine.execute_step(
            {
                "id": "final_check",
                "operation": "read_savings_balance",
                "action": {
                    "action": "verify",
                    "condition": CAPABILITY.success_checkpoint.model_dump(),
                },
            }
        )
        assert checkpoint.status == "success"
        observation = await engine.observe()
        assert balance not in json.dumps(observation)
        for kind in ("artifact_diagnostic", "human_event", "model_explanation", "error"):
            engine.store.diagnostic(
                kind,
                {
                    "secret-key-jane@example.com": {
                        "description": "unregistered-secret-xyz",
                        "value": balance,
                        "number": 123456789,
                    }
                },
            )
        evidence = all_evidence(engine)
        for secret in (
            member,
            balance,
            "Jane Doe",
            "jane@example.com",
            "sk-do-not-store",
            "unregistered-secret-xyz",
            "123456789",
        ):
            assert secret not in evidence
        completed = [e for e in events(engine) if e["event"] == "completed"]
        assert len(completed) == 8
        assert all(e["mode"] == mode and e["policy_decision"] == "allowed" for e in completed)
        assert completed[-1]["checkpoint"] == "passed"
        assert ("POST", "/members") in bank["requests"]


@pytest.mark.parametrize(
    ("operation", "action"),
    [
        ("transfer_money", {"action": "navigate", "path": "/"}),
        ("search_member", {"action": "navigate", "path": "/demo"}),
        (
            "search_member",
            {
                "action": "click",
                "target": {
                    "strategy": "role",
                    "role": "button",
                    "name": {"source": "literal", "value": "Transfer"},
                    "rationale": "Safe because the model says so",
                },
            },
        ),
        (
            "search_member",
            {
                "action": "read",
                "output": "secrets",
                "target": {
                    "strategy": "css",
                    "selector": "input[type=password]",
                    "rationale": "Read passwords",
                },
            },
        ),
    ],
)
@async_test
async def test_disallowed_operations_actions_and_routes(bank, tmp_path, operation, action):
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        before = list(bank["requests"])
        outcome = await engine.execute_step(
            {"id": "denied", "operation": operation, "action": action}
        )
        assert outcome.code == "policy_denied"
        assert bank["requests"] == before
        assert events(engine)[-1]["policy_decision"] == "denied"
        snapshot = json.loads(
            (engine.store.directory / (outcome.diagnostic.evidence_ref + ".json")).read_text()
        )
        assert "dom_structure" in json.dumps(snapshot)
        assert '"tag": "form"' in json.dumps(snapshot)
        assert "Avery" not in json.dumps(snapshot)


@pytest.mark.parametrize(
    "destination",
    ["/transfer", "http://127.0.0.1:1/exfiltrate", "/members?token=secret", "/%2e%2e/transfer"],
)
@async_test
async def test_redirects_are_blocked_before_destination_request(bank, tmp_path, destination):
    bank["redirect"] = destination
    async with executor(bank, tmp_path) as engine:
        outcome = await engine.execute_step(CAPABILITY.steps[0])
        assert outcome.code == "policy_denied"
        assert bank["requests"] == [("GET", "/")]
        assert "secret" not in all_evidence(engine)


@pytest.mark.parametrize(
    "mutation",
    [
        "document.querySelector('form').action = '/transfer'",
        "document.querySelector('button').setAttribute('formaction', '/transfer')",
        "document.querySelector('button').setAttribute('formmethod', 'delete')",
        "document.querySelector('button').setAttribute('formtarget', '_blank')",
        "document.querySelector('button').textContent = 'Delete account'; document.querySelector('button').setAttribute('aria-label', 'Search')",
    ],
)
@async_test
async def test_spoofed_safe_control_cannot_perform_risky_operation(bank, tmp_path, mutation):
    async with executor(bank, tmp_path) as engine:
        for step in CAPABILITY.steps[:2]:
            assert (await engine.execute_step(step)).status == "success"
        await engine._session._page.evaluate(mutation)
        outcome = await engine.execute_step(CAPABILITY.steps[2])
        assert outcome.code == "policy_denied"
        assert not any(method != "GET" for method, _ in bank["requests"])


@async_test
async def test_click_handler_navigation_cannot_bypass_href_check(bank, tmp_path):
    async with executor(bank, tmp_path) as engine:
        for step in CAPABILITY.steps[:3]:
            assert (await engine.execute_step(step)).status == "success"
        await engine._session._page.evaluate(
            "() => { document.querySelector('a[href=\"/members/1001\"]').onclick = e => { e.preventDefault(); location.href='/transfer'; }; }"
        )
        outcome = await engine.execute_step(CAPABILITY.steps[3])
        assert outcome.code == "policy_denied"
        assert ("GET", "/transfer") not in bank["requests"]


@pytest.mark.parametrize(
    "script",
    [
        "fetch('/members/1001/accounts').catch(() => {})",
        "fetch('/members', {method: 'POST', body: 'secret'}).catch(() => {})",
        "let f = document.createElement('iframe'); f.src='/members/1001'; document.body.append(f)",
        "window.open('/members/1001')",
        "new WebSocket('ws://127.0.0.1:1/private')",
    ],
)
@async_test
async def test_background_fetch_frames_popups_and_sockets_are_blocked(bank, tmp_path, script):
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        await engine._session._page.evaluate(script)
        # Wait for a guard event, not an arbitrary UI delay.
        async with asyncio.timeout(2):
            while not engine._session._boundary.blocked:
                await asyncio.sleep(0.01)
        assert (await engine.execute_step(CAPABILITY.steps[1])).code == "policy_denied"
        assert all(
            path in {"/", "/static/app.js", "/static/styles.css"} for _, path in bank["requests"]
        )


@async_test
async def test_ambiguous_control_yields_sanitized_richer_failure_and_no_click(bank, tmp_path):
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        await engine._session._page.evaluate(
            "document.querySelector('form').append(document.querySelector('button').cloneNode(true)); document.body.insertAdjacentHTML('beforeend', '<p>Secret Person secret@example.com 4111111111111111</p><input type=password value=private-token>')"
        )
        outcome = await engine.execute_step(CAPABILITY.steps[2])
        assert outcome.code == "ambiguous_target"
        text = all_evidence(engine)
        assert "dom_structure" in text and '"tag": "button"' in text
        assert all(
            value not in text
            for value in (
                "Secret Person",
                "secret@example.com",
                "4111111111111111",
                "private-token",
            )
        )
        assert not any(method == "POST" for method, _ in bank["requests"])


@async_test
async def test_human_ownership_control_events_and_direct_adapter_bypass(bank, tmp_path):
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        with pytest.raises(SurfaceError, match="policy_denied"):
            await engine._session.surface.execute(CAPABILITY.steps[1].action, {"member_id": "1001"})
        await engine.transition("AWAITING_HUMAN", "Sensitive operator explanation")
        await engine.transition("HUMAN_CONTROL", "Human enters password abc123")
        assert (await engine.execute_step(CAPABILITY.steps[1])).code == "ownership_denied"
        assert "abc123" not in all_evidence(engine)
        assert len([e for e in events(engine) if e["event"] == "control_change"]) == 2
        assert events(engine)[-1]["policy_decision"] == "not_checked"


@async_test
async def test_precondition_blocks_side_effect_and_postcondition_blocks_output(bank, tmp_path):
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        step = CAPABILITY.steps[4].model_dump()
        step["precondition"] = step.pop("postcondition")
        assert (await engine.execute_step(step)).code == "checkpoint_failed"
        for step in CAPABILITY.steps[1:]:
            assert (await engine.execute_step(step)).status == "success"
        await engine._session._page.locator(".accounts-member-id").evaluate(
            "el => el.textContent = '9999'"
        )
        step = CAPABILITY.steps[5].model_dump()
        step["postcondition"] = CAPABILITY.success_checkpoint.model_dump()
        outcome = await engine.execute_step(step)
        assert outcome.code == "checkpoint_failed" and outcome.output is None
        assert events(engine)[-1]["checkpoint"] == "failed"


@async_test
async def test_wait_retry_and_limits_are_enforced(bank, tmp_path):
    async with executor(bank, tmp_path, max_steps=5) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        wait = {
            "id": "wait_member",
            "operation": "open_member",
            "action": {
                "action": "wait",
                "timeout_ms": 30,
                "condition": {
                    "kind": "visible",
                    "target": CAPABILITY.steps[3].action.target.model_dump(),
                },
            },
        }
        assert (await engine.execute_step(wait)).code == "timeout"
        assert (await engine.execute_step(wait, retry=1)).code == "timeout"
        assert (await engine.execute_step(wait, retry=2)).code == "timeout"
        assert (await engine.execute_step(wait, retry=3)).code == "invalid_input"
        assert (await engine.execute_step(CAPABILITY.steps[2], retry=1)).code == "policy_denied"
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        assert (await engine.execute_step(CAPABILITY.steps[0])).code == "step_limit"
    async with executor(bank, tmp_path) as engine:
        engine._started_at -= 121
        assert (await engine.execute_step(CAPABILITY.steps[0])).code == "timeout"


@async_test
async def test_persistence_failure_stops_browser_before_next_action(bank, tmp_path, monkeypatch):
    async with executor(bank, tmp_path) as engine:

        def failed(*args, **kwargs):
            raise PersistenceError()

        monkeypatch.setattr(engine.store, "_write", failed)
        with pytest.raises(PersistenceError):
            await engine.execute_step(CAPABILITY.steps[0])
        assert not engine._session._browser  # Explicit cleanup cleared the browser.
        assert bank["requests"] == []


@async_test
async def test_target_identity_and_config_mutation_cannot_widen_permissions(bank, tmp_path):
    configuration = config(bank)
    engine = Executor(
        configuration=configuration,
        project_root=tmp_path,
        mode="discovery",
        inputs={"member_id": "1001"},
    )
    configuration.policy.navigation.append(
        configuration.policy.navigation[0].model_copy(update={"path": "^/transfer$"})
    )
    async with engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        await engine._session._page.evaluate(
            "document.documentElement.dataset.version = 'evil-version'"
        )
        assert (await engine.execute_step(CAPABILITY.steps[1])).code == "incompatible_target"


@async_test
async def test_every_redirect_hop_is_checked(bank, tmp_path):
    bank["redirect"] = "/members/1001"
    bank["second_redirect"] = "/transfer"
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).code == "policy_denied"
        assert bank["requests"] == [("GET", "/"), ("GET", "/members/1001")]


@async_test
async def test_attachment_response_is_blocked_and_not_saved(bank, tmp_path):
    bank["download"] = True
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).code == "policy_denied"
        assert "secret-file-contents" not in all_evidence(engine)


@async_test
async def test_password_field_disguised_with_approved_label_is_rejected(bank, tmp_path):
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        await engine._session._page.locator("#member-id").evaluate("el => el.type = 'password'")
        assert (await engine.execute_step(CAPABILITY.steps[1])).code == "policy_denied"
        assert await engine._session._page.locator("#member-id").input_value() == ""


@async_test
async def test_cancelled_wait_records_failure_and_preserves_live_session(bank, tmp_path):
    async with executor(bank, tmp_path) as engine:
        assert (await engine.execute_step(CAPABILITY.steps[0])).status == "success"
        wait = {
            "id": "wait_member",
            "operation": "open_member",
            "action": {
                "action": "wait",
                "timeout_ms": 5000,
                "condition": {
                    "kind": "visible",
                    "target": CAPABILITY.steps[3].action.target.model_dump(),
                },
            },
        }
        entered = asyncio.Event()
        original = engine._session.surface._evaluate

        async def signalled(*args):
            entered.set()
            return await original(*args)

        engine._session.surface._evaluate = signalled
        task = asyncio.create_task(engine.execute_step(wait))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert events(engine)[-1]["details"]["code"] == "cancelled"
        assert not engine._session._page.is_closed()

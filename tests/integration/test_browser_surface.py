"""Real Chromium integration; direct page access only simulates target/operator behavior."""

import asyncio
from functools import wraps
from pathlib import Path
from threading import Thread
from time import monotonic

import pytest
from werkzeug.serving import make_server

from computer_use.schemas.capability import Capability, TargetIdentity
from computer_use.sessions.manager import BrowserSession
from computer_use.surfaces.base import SurfaceError
from mock_app.app import create_app

IDENTITY = TargetIdentity(product="synthetic_bank", version="1.0", surface="browser")
FIXTURE = Path(__file__).parents[1] / "fixtures/read_savings_balance.json"


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


@pytest.fixture(scope="module")
def bank_url():
    server = make_server(
        "127.0.0.1", 0, create_app({"TESTING": True, "SLOW_LOAD_MS": 400}), threaded=True
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def session(bank_url, **kwargs):
    return BrowserSession(
        base_url=bank_url, target=IDENTITY, run_id="adapter_test", headless=True, **kwargs
    )


def literal(value):
    return {"source": "literal", "value": value}


def role(name, kind="button", **kwargs):
    return {
        "strategy": "role",
        "role": kind,
        "name": literal(name),
        "rationale": "Test exact role",
        **kwargs,
    }


def css(selector, **kwargs):
    return {"strategy": "css", "selector": selector, "rationale": "Test explicit CSS", **kwargs}


def visible(target):
    return {"kind": "visible", "target": target}


async def scenario(browser_session, name):
    # Operator-only setup, outside the adapter's action API.
    page = browser_session._page
    await page.goto(browser_session._base_url + "/demo")
    await page.get_by_label("Scenario", exact=True).select_option(name)
    await page.get_by_role("button", name="Apply scenario", exact=True).click()


@pytest.mark.parametrize(("member", "balance"), [("1001", "1250.75"), ("2002", "8040.20")])
@async_test
async def test_fixture_operations_read_current_ui(bank_url, member, balance):
    capability = Capability.model_validate_json(FIXTURE.read_text())
    inputs = capability.validate_inputs({"member_id": member})
    outputs = {}
    async with session(bank_url) as live:
        page = live._page
        for step in capability.steps:
            result = await live.surface.execute(step.action, inputs, timeout_ms=step.timeout_ms)
            if step.action.action == "read":
                outputs[step.action.output] = result
            if step.postcondition:
                assert await live.surface.evaluate(step.postcondition, inputs)
        await live.surface.execute(
            {"action": "verify", "condition": capability.success_checkpoint.model_dump()}, inputs
        )
        assert outputs == {"balance": balance, "currency": "USD"}
        capability.validate_outputs(outputs)
        observation = await live.surface.observe()
        assert observation.target == IDENTITY
        assert observation.session_id == live.session_id
        assert observation.run_id == "adapter_test"
        assert observation.state == "ready"
        assert balance in observation.summary
        assert observation.location == f"/members/{member}/accounts"
        assert observation.controls
        assert (await live.surface.observe()).sequence == observation.sequence + 1
        assert live._page is page


@async_test
async def test_observation_reports_real_accessible_controls(bank_url):
    async with session(bank_url) as live:
        await live.surface.execute({"action": "navigate", "path": "/"})
        observation = await live.surface.observe()
        names = {(c.target.role, c.target.name.value) for c in observation.controls}
        assert ("textbox", "Member ID") in names
        assert ("button", "Search") in names
        for control in observation.controls:
            assert await live.surface.evaluate(visible(control.target.model_dump()))
        await live._page.goto(bank_url + "/?token=do-not-report#private")
        assert (await live.surface.observe()).location == "/"


@pytest.mark.parametrize(
    ("target", "code"),
    [
        (role("Missing"), "target_not_found"),
        (role("Same"), "ambiguous_target"),
        (css("button", scope=".group"), "ambiguous_target"),
        (css("button", scope="#absent"), "target_not_found"),
        (css("button >> nth=0"), "unsupported_target"),
        (css("xpath=//button"), "unsupported_target"),
        (css("[invalid"), "browser_error"),
    ],
)
@async_test
async def test_unsafe_targeting_never_clicks(bank_url, target, code):
    async with session(bank_url) as live:
        await live._page.set_content(
            '<div class="group"><button>Same</button></div><div class="group"><button>Same</button></div>'
        )
        await live._page.evaluate(
            "window.clicks = 0; document.addEventListener('click', () => window.clicks++)"
        )
        with pytest.raises(SurfaceError) as caught:
            await live.surface.execute({"action": "click", "target": target})
        assert caught.value.code == code
        assert await live._page.evaluate("window.clicks") == 0


@async_test
async def test_scoped_roles_labels_text_and_css_are_exact(bank_url):
    async with session(bank_url) as live:
        await live._page.set_content("""
            <section id="first"><label>Code<input></label><button>Save</button></section>
            <section id="second"><label>Code<input></label><button>Save</button><p>Answer</p></section>
            <button>Save changes</button>""")
        await live.surface.execute(
            {
                "action": "fill",
                "target": {
                    "strategy": "label",
                    "label": literal("Code"),
                    "scope": "#second",
                    "rationale": "Scoped label",
                },
                "value": literal("new value"),
            }
        )
        assert await live._page.locator("#first input").input_value() == ""
        assert await live._page.locator("#second input").input_value() == "new value"
        await live._page.evaluate(
            "document.querySelector('#second button').onclick = () => document.querySelector('p').textContent = 'Saved'"
        )
        await live.surface.execute({"action": "click", "target": role("Save", scope="#second")})
        assert (
            await live.surface.execute(
                {
                    "action": "read",
                    "output": "answer",
                    "target": {
                        "strategy": "text",
                        "text": literal("Saved"),
                        "scope": "#second",
                        "rationale": "Exact text",
                    },
                }
            )
            == "Saved"
        )
        assert (
            await live.surface.execute(
                {"action": "read", "output": "answer", "target": css("#second p")}
            )
            == "Saved"
        )
        assert not await live.surface.evaluate(visible(role("Save change")))


@async_test
async def test_conditions_have_explicit_missing_hidden_and_ambiguous_semantics(bank_url):
    async with session(bank_url) as live:
        await live._page.set_content(
            '<p id="hidden" hidden>Secret</p><p class="duplicate">A</p><p class="duplicate">B</p><p id="answer">  Yes  </p>'
        )
        assert not await live.surface.evaluate(visible(css("#missing")))
        assert await live.surface.evaluate({"kind": "hidden", "target": css("#missing")})
        assert await live.surface.evaluate({"kind": "hidden", "target": css("#hidden")})
        assert await live.surface.evaluate(
            {"kind": "text_equals", "target": css("#answer"), "expected": literal("Yes")}
        )
        with pytest.raises(SurfaceError, match="ambiguous_target"):
            await live.surface.evaluate({"kind": "hidden", "target": css(".duplicate")})
        with pytest.raises(SurfaceError, match="target_not_visible"):
            await live.surface.execute(
                {"action": "read", "output": "secret", "target": css("#hidden")}
            )
        with pytest.raises(SurfaceError, match="checkpoint_failed"):
            await live.surface.execute({"action": "verify", "condition": visible(css("#missing"))})


@async_test
async def test_real_slow_loading_waits_for_results(bank_url):
    async with session(bank_url) as live:
        await scenario(live, "slow_loading")
        await live.surface.execute(
            {"action": "fill", "target": css("#member-id"), "value": literal("1001")}
        )
        await live.surface.execute({"action": "click", "target": role("Search")})
        assert (await live.surface.observe()).state == "loading"
        await live.surface.execute(
            {"action": "wait", "condition": visible(role("1001", "link")), "timeout_ms": 2000}
        )
        assert await live.surface.evaluate({"kind": "hidden", "target": css("[role=status]")})
        await live.surface.execute({"action": "click", "target": role("1001", "link")})
        assert (await live.surface.observe()).location == "/members/1001"


@async_test
async def test_wait_deadline_is_bounded_and_session_remains_usable(bank_url):
    async with session(bank_url) as live:
        await live.surface.execute({"action": "navigate", "path": "/"})
        started = monotonic()
        with pytest.raises(SurfaceError, match="timeout"):
            await live.surface.execute(
                {"action": "wait", "condition": visible(css("#absent")), "timeout_ms": 1000},
                timeout_ms=120,
            )
        assert monotonic() - started < 0.8
        assert await live.surface.evaluate(visible(role("Search")))
        await live._page.evaluate(
            "setTimeout(() => document.querySelector('h1').textContent = 'Changed', 80)"
        )
        await live.surface.execute(
            {
                "action": "wait",
                "condition": {
                    "kind": "text_equals",
                    "target": css("h1"),
                    "expected": literal("Changed"),
                },
                "timeout_ms": 1000,
            }
        )


@pytest.mark.parametrize(
    "action",
    [
        {"action": "navigate", "path": "/"},
        {"action": "fill", "target": css("#member-id"), "value": literal("2002")},
        {"action": "click", "target": role("Search")},
        {"action": "read", "target": css("h1"), "output": "heading"},
        {"action": "wait", "condition": visible(css("h1")), "timeout_ms": 100},
        {"action": "verify", "condition": visible(css("h1"))},
    ],
)
@async_test
async def test_human_ownership_blocks_every_dispatch(bank_url, action):
    async with session(bank_url) as live:
        await live.surface.execute({"action": "navigate", "path": "/"})
        await live.control.transition("AWAITING_HUMAN", "Test pause")
        with pytest.raises(SurfaceError, match="ownership_denied"):
            await live.surface.execute(action)
        await live.control.transition("HUMAN_CONTROL", "Test takeover")
        with pytest.raises(SurfaceError, match="ownership_denied"):
            await live.surface.execute(action)
        with pytest.raises(SurfaceError, match="ownership_denied"):
            await live.surface.observe()
        with pytest.raises(SurfaceError, match="ownership_denied"):
            await live.surface.evaluate(visible(css("h1")))
        assert live._page.url == bank_url + "/"


@async_test
async def test_takeover_preserves_page_cookies_and_requires_resume_state(bank_url):
    async with session(bank_url) as live:
        await scenario(live, "unexpected_dialog")
        capability = Capability.model_validate_json(FIXTURE.read_text())
        for step in capability.steps[:5]:
            await live.surface.execute(step.action, {"member_id": "1001"})
        assert (await live.surface.observe()).state == "unexpected_dialog"
        page, context, session_id = live._page, live._context, live.session_id
        await live.control.transition("AWAITING_HUMAN", "Unknown dialog")
        await live.control.transition("HUMAN_CONTROL", "Operator takes control")
        # Simulated person uses the existing page; no new browser/context is created.
        await page.get_by_role("button", name="Continue to accounts", exact=True).click()
        await live.control.transition("RESUME_CHECK", "Operator returns control")
        assert (await live.surface.observe()).state == "ready"
        with pytest.raises(SurfaceError, match="ownership_denied"):
            await live.surface.execute({"action": "click", "target": role("Members", "link")})
        await live.surface.execute(
            {"action": "verify", "condition": capability.success_checkpoint.model_dump()},
            {"member_id": "1001"},
        )
        await live.control.transition("AUTOMATION_RUNNING", "Checkpoint passed")
        assert await live.surface.execute(capability.steps[5].action) == "1250.75"
        await live.surface.execute({"action": "navigate", "path": "/members/1001/accounts"})
        assert (await live.surface.observe()).state == "ready"  # Acknowledgement cookie survived.
        assert live._page is page and live._context is context and live.session_id == session_id


@async_test
async def test_transfer_serializes_with_active_operation_and_blocks_queued_action(bank_url):
    async with session(bank_url) as live:
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(route):
            entered.set()
            await release.wait()
            await route.continue_()

        await live._page.route("**/members/1001", delayed)
        operation = asyncio.create_task(
            live.surface.execute({"action": "navigate", "path": "/members/1001"})
        )
        await asyncio.wait_for(entered.wait(), 2)
        transfer = asyncio.create_task(
            live.control.transition("AWAITING_HUMAN", "Concurrent pause")
        )
        queued = asyncio.create_task(live.surface.execute({"action": "navigate", "path": "/"}))
        await asyncio.sleep(0)  # Schedule contenders; not a UI readiness wait.
        assert not transfer.done()
        release.set()
        await operation
        await transfer
        with pytest.raises(SurfaceError, match="ownership_denied"):
            await queued
        assert live._page.url.endswith("/members/1001")


@async_test
async def test_cancelled_mutation_closes_context_before_ownership_can_transfer(bank_url):
    async with session(bank_url) as live:
        entered = asyncio.Event()

        async def stalled(route):
            entered.set()
            # Leave request pending; closing the context must cancel it.

        await live._page.route("**/members/1001", stalled)
        operation = asyncio.create_task(
            live.surface.execute({"action": "navigate", "path": "/members/1001"})
        )
        await asyncio.wait_for(entered.wait(), 2)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert live._page.is_closed()
        with pytest.raises(SurfaceError, match="session_closed"):
            await live.control.transition("AWAITING_HUMAN", "No unsafe transfer")


@async_test
async def test_explicit_shutdown_and_external_close_are_terminal(bank_url):
    live = session(bank_url)
    with pytest.raises(SurfaceError, match="session_not_started"):
        _ = live.surface
    await live.start()
    assert await live.start() is live
    surface, browser = live.surface, live._browser
    await live.close()
    await live.close()
    assert not browser.is_connected()
    with pytest.raises(SurfaceError, match="session_closed"):
        await surface.execute({"action": "navigate", "path": "/"})
    with pytest.raises(SurfaceError, match="session_closed"):
        await live.start()
    async with session(bank_url) as other:
        surface = other.surface
        await other._page.close()
        with pytest.raises(SurfaceError, match="session_closed"):
            await surface.observe()


@async_test
async def test_contexts_are_isolated_and_exceptions_close_browser(bank_url):
    first, second = session(bank_url), session(bank_url)
    with pytest.raises(RuntimeError, match="caller failed"):
        async with first, second:
            await scenario(first, "permission_denied")
            for live in (first, second):
                await live.surface.execute({"action": "navigate", "path": "/members/1001/accounts"})
            assert (await first.surface.observe()).state == "permission_denied"
            assert (await second.surface.observe()).state == "ready"
            assert first.session_id != second.session_id
            browsers = first._browser, second._browser
            raise RuntimeError("caller failed")
    assert all(not browser.is_connected() for browser in browsers)


@pytest.mark.parametrize(
    "operation",
    [
        {"action": "delete"},
        {"action": "navigate", "path": "https://example.com"},
        {
            "action": "fill",
            "target": css("input"),
            "value": {"source": "input", "ref": "inputs.secret"},
        },
    ],
)
@async_test
async def test_invalid_contracts_fail_before_browser_dispatch(bank_url, operation):
    async with session(bank_url) as live:
        with pytest.raises(SurfaceError, match="invalid_input"):
            await live.surface.execute(operation)
        assert live._page.url == "about:blank"


@async_test
async def test_observation_rejects_incompatible_ui_and_driver_errors_do_not_echo_secrets(bank_url):
    async with session(bank_url) as live:
        with pytest.raises(SurfaceError, match="incompatible_target"):
            await live.surface.observe()
        await live._page.set_content('<input disabled aria-label="Secret">')
        with pytest.raises(SurfaceError) as caught:
            await live.surface.execute(
                {
                    "action": "fill",
                    "target": role("Secret", "textbox"),
                    "value": literal("do-not-expose"),
                },
                timeout_ms=80,
            )
        assert caught.value.code == "timeout"
        assert "do-not-expose" not in str(caught.value)


@async_test
async def test_illegal_transitions_and_terminal_ownership(bank_url):
    async with session(bank_url) as live:
        with pytest.raises(ValueError):
            await live.control.transition("HUMAN_CONTROL", "Cannot skip pause")
        assert live.control.snapshot.state == "AUTOMATION_RUNNING"
        await live.control.transition("COMPLETED", "Done")
        with pytest.raises(SurfaceError, match="ownership_denied"):
            await live.surface.execute({"action": "navigate", "path": "/"})
        with pytest.raises(ValueError):
            await live.control.transition("AUTOMATION_RUNNING", "Cannot revive")

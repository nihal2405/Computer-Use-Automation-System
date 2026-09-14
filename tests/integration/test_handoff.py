"""Real browser events from simulated operators; manual runs are labelled separately."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from test_discovery import agent
from test_replay import ARTIFACT, CapabilityStore, async_test, engine

from computer_use.handoff.coordinator import HandoffCoordinator
from computer_use.handoff.operator import OperatorServer
from computer_use.observability.evidence import PersistenceError
from computer_use.schemas.capability import Capability
from computer_use.schemas.intervention import Intervention


@asynccontextmanager
async def paused(bank, tmp_path, *, discovery=False, capability=None, wait_timeout=20):
    bank["scenario"] = "unexpected_dialog"
    runner = agent(bank, tmp_path) if discovery else engine(bank, tmp_path, capability=capability)
    async with runner:
        coordinator = HandoffCoordinator(runner, wait_timeout=wait_timeout)
        task = asyncio.create_task(runner.run())
        try:
            await asyncio.wait_for(coordinator.ready.wait(), 8)
            yield runner, coordinator, task
        finally:
            if not task.done():
                try:
                    await coordinator.command("cancel")
                except Exception:
                    task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def events(runner):
    return [
        json.loads(line)
        for line in (runner.executor.store.directory / "events.jsonl").read_text().splitlines()
    ]


def resolutions(runner):
    result = []
    for path in runner.executor.store.directory.glob("*.json"):
        data = json.loads(path.read_text())
        if data.get("resolution"):
            result.append(Intervention.model_validate(data))
    return result


@async_test
async def test_operator_ui_transfers_same_session_and_captures_real_browser_events(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        page = runner.executor._session._page
        session = runner.executor.session_id
        server = OperatorServer(control)
        try:
            async with httpx.AsyncClient(
                base_url=server.origin, headers={"Authorization": "Bearer " + server.token}
            ) as client:
                assert (await client.get("/api/state")).json()["state"] == "AWAITING_HUMAN"
                assert (
                    await client.post("/api/command", json={"command": "resume"})
                ).status_code == 409
                assert (await client.post("/api/command", json={"command": "takeover"})).json()[
                    "state"
                ] == "HUMAN_CONTROL"
                assert (
                    await runner.executor.execute_step(runner.capability.steps[0])
                ).code == "ownership_denied"
                await page.get_by_role("button", name="Continue to accounts", exact=True).click()
                await page.locator("td.savings-balance").wait_for()
                assert (await client.post("/api/command", json={"command": "resume"})).json()[
                    "state"
                ] == "AUTOMATION_RUNNING"
            result = await asyncio.wait_for(run, 5)
            assert result.status == "success" and result.outputs["balance"] == "8040.20", result
            assert runner.executor.session_id == session and runner.executor._session._page is page
            assert bank["requests"].count(("POST", "/members/2002/accounts")) == 1
            interactions = [e for e in events(runner) if e["event"] == "human_interaction"]
            assert any(e["details"].get("interaction") == "click" for e in interactions)
            assert any(e["details"].get("interaction") == "navigation" for e in interactions)
            assert resolutions(runner)[0].resolution.state_verified
            assert resolutions(runner)[0].resolution.action == "resume"
        finally:
            await server.close()


@async_test
async def test_unexpected_page_rejects_resume_then_operator_can_correct_it(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")
        page = runner.executor._session._page
        await page.goto(bank["url"] + "/")
        before = len([e for e in events(runner) if e["event"] == "started"])
        assert (await control.command("resume"))["state"] == "AWAITING_HUMAN"
        assert not run.done()
        assert len([e for e in events(runner) if e["event"] == "started"]) == before
        await control.command("takeover")
        await page.goto(bank["url"] + "/members/2002/accounts")
        await page.get_by_role("button", name="Continue to accounts", exact=True).click()
        await control.command("resume")
        assert (await asyncio.wait_for(run, 5)).status == "success"


@async_test
async def test_human_can_complete_interrupted_navigation_without_repeating_it(bank, tmp_path):
    data = CapabilityStore.load(ARTIFACT).model_dump()
    # Deliberately stop before navigation. A generated artifact need not contain
    # the development fixture's optional postcondition; construct the reviewed
    # condition explicitly so this scenario exercises either artifact equally.
    accounts_step = next(step for step in data["steps"] if step["operation"] == "open_accounts")
    accounts_step["precondition"] = {
        "kind": "visible",
        "target": {
            "strategy": "role",
            "role": "heading",
            "name": {"source": "literal", "value": "Accounts"},
            "rationale": "Test obstacle before account navigation",
        },
    }
    async with paused(bank, tmp_path, capability=Capability.model_validate(data)) as (
        runner,
        control,
        run,
    ):
        assert not any(path.endswith("/accounts") for _, path in bank["requests"])
        await control.command("takeover")
        page = runner.executor._session._page
        await page.get_by_role("link", name="Accounts", exact=True).click()
        await page.get_by_role("button", name="Continue to accounts", exact=True).click()
        await control.command("resume")
        assert (await asyncio.wait_for(run, 5)).status == "success"
        assert (
            bank["requests"].count(("GET", "/members/2002/accounts")) == 2
        )  # Click plus acknowledgement redirect, no repeated automation click.


@pytest.mark.parametrize("takeover", [False, True])
@async_test
async def test_cancel_from_paused_or_human_control_is_terminal(bank, tmp_path, takeover):
    async with paused(bank, tmp_path) as (runner, control, run):
        if takeover:
            await control.command("takeover")
        await control.command("cancel")
        result = await asyncio.wait_for(run, 5)
        assert result.code == "cancelled" and runner.executor.control.state == "FAILED"
        assert resolutions(runner)[0].resolution.action == "abort"
        assert not any(e["event"] == "started" and e["action"] == "read" for e in events(runner))


@async_test
async def test_human_input_values_never_enter_event_payloads_or_disk(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")
        page = runner.executor._session._page
        await page.evaluate(
            "document.querySelector('dialog').insertAdjacentHTML('beforeend','<input aria-label=Secret type=password>')"
        )
        await page.get_by_label("Secret").click()
        await page.get_by_label("Secret").press_sequentially("super-private-password-123")
        await control.capture.flush()
        await control.command("cancel")
        await run
        text = "\n".join(p.read_text() for p in runner.executor.store.directory.iterdir())
        assert "super-private-password-123" not in text and '"value"' not in json.dumps(
            [e for e in events(runner) if e["event"] == "human_interaction"]
        )
        assert any(
            e["details"].get("interaction") == "input"
            for e in events(runner)
            if e["event"] == "human_interaction"
        )


@async_test
async def test_operator_api_rejects_foreign_origins_hosts_and_tokens(bank, tmp_path):
    async with paused(bank, tmp_path) as (_, control, _):
        server = OperatorServer(control)
        try:
            async with httpx.AsyncClient(base_url=server.origin) as client:
                assert (await client.get("/api/state")).status_code == 403
                assert (
                    await client.get("/api/state", headers={"Authorization": "Bearer wrong"})
                ).status_code == 403
                good = {"Authorization": "Bearer " + server.token}
                assert (
                    await client.post(
                        "/api/command",
                        headers={**good, "Origin": "https://evil.example"},
                        json={"command": "cancel"},
                    )
                ).status_code == 403
                assert (
                    await client.get("/api/state", headers={**good, "Host": "evil.example"})
                ).status_code == 403
                assert (
                    await client.post("/api/command", headers=good, json={"command": "execute"})
                ).status_code == 400
                response = await client.get("/api/state", headers=good)
                assert (
                    response.status_code == 200 and response.headers["Cache-Control"] == "no-store"
                )
        finally:
            await server.close()


@async_test
async def test_discovery_handoff_returns_verified_outputs_without_fabricating_artifact(
    bank, tmp_path
):
    async with paused(bank, tmp_path, discovery=True) as (runner, control, run):
        model_calls = len(runner.model.contexts)
        await control.command("takeover")
        await runner.executor._session._page.get_by_role(
            "button", name="Continue to accounts", exact=True
        ).click()
        await control.command("resume")
        result = await asyncio.wait_for(run, 5)
        assert result.status == "success" and result.outputs["balance"] == "1250.75", result
        assert runner.human_assisted and runner.artifact_path is None
        assert len(runner.model.contexts) == model_calls


@async_test
async def test_operator_wait_does_not_consume_active_execution_budget(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        runner.executor._started_at -= 121
        control._wait_started -= 121
        await control.command("takeover")
        await runner.executor._session._page.get_by_role(
            "button", name="Continue to accounts", exact=True
        ).click()
        await control.command("resume")
        assert (await asyncio.wait_for(run, 5)).status == "success"


@async_test
async def test_operator_deadline_cancels_the_run(bank, tmp_path):
    async with paused(bank, tmp_path, wait_timeout=1) as (runner, control, run):
        assert (await asyncio.wait_for(run, 3)).code == "cancelled"


@async_test
async def test_capture_persistence_failure_stops_instead_of_losing_human_history(
    bank, tmp_path, monkeypatch
):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")

        def broken(*args, **kwargs):
            raise PersistenceError()

        monkeypatch.setattr(runner.executor.store, "_write", broken)
        page = runner.executor._session._page
        try:
            await page.get_by_role("button", name="Continue to accounts", exact=True).click()
        except Exception:
            pass  # Closing immediately on audit failure can interrupt the click.
        result = await asyncio.wait_for(run, 5)
        assert result.code == "persistence_failed"
        assert runner.executor._session._browser is None


@pytest.mark.parametrize(
    "mutation",
    [
        "document.querySelector('.accounts-member-id').textContent='9999'",
        "document.querySelector('td.savings-balance').remove()",
    ],
)
@async_test
async def test_wrong_owner_or_missing_output_prevents_resume(bank, tmp_path, mutation):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")
        page = runner.executor._session._page
        await page.get_by_role("button", name="Continue to accounts", exact=True).click()
        await page.evaluate(mutation)
        assert (await control.command("resume"))["state"] == "AWAITING_HUMAN"
        assert not run.done()


@async_test
async def test_dialog_cannot_be_acknowledged_before_takeover(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        await runner.executor._session._page.get_by_role(
            "button", name="Continue to accounts", exact=True
        ).click()
        assert not any(
            method == "POST" and path.endswith("/accounts") for method, path in bank["requests"]
        )
        assert runner.executor.control.state == "AWAITING_HUMAN"


@async_test
async def test_human_permission_cannot_be_used_for_another_member_or_payload(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")
        page = runner.executor._session._page
        await page.evaluate("document.querySelector('form').action='/members/1001/accounts'")
        try:
            await page.get_by_role("button", name="Continue to accounts", exact=True).click()
        except Exception:
            pass
        assert ("POST", "/members/1001/accounts") not in bank["requests"]


@async_test
async def test_duplicate_resume_is_rejected_and_outputs_are_read_once(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")
        await runner.executor._session._page.get_by_role(
            "button", name="Continue to accounts", exact=True
        ).click()
        responses = await asyncio.gather(
            control.command("resume"), control.command("resume"), return_exceptions=True
        )
        assert sum(isinstance(item, ValueError) for item in responses) == 1
        assert (await asyncio.wait_for(run, 5)).status == "success"
        assert (
            len([e for e in events(runner) if e["event"] == "completed" and e["action"] == "read"])
            == 2
        )


@async_test
async def test_closed_bank_window_can_still_be_cancelled(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")
        await runner.executor._session._page.close()
        assert (await control.command("cancel"))["state"] == "FAILED"
        assert (await asyncio.wait_for(run, 5)).code == "cancelled"
        assert resolutions(runner)[0].resolution.action == "abort"


@async_test
async def test_interrupted_verification_closes_browser_and_cancels(bank, tmp_path, monkeypatch):
    async with paused(bank, tmp_path) as (runner, control, run):
        await control.command("takeover")
        checking = asyncio.Event()

        async def interrupted():
            checking.set()
            await asyncio.Future()

        monkeypatch.setattr(control, "_verify_resume", interrupted)
        command = asyncio.create_task(control.command("resume"))
        await asyncio.wait_for(checking.wait(), 3)
        command.cancel()
        await asyncio.gather(command, return_exceptions=True)
        assert (await asyncio.wait_for(run, 5)).code == "cancelled"
        assert runner.executor._session._browser is None


@async_test
async def test_resume_entry_point_requires_verified_one_use_ticket(bank, tmp_path):
    async with paused(bank, tmp_path) as (runner, control, run):
        with pytest.raises(ValueError, match="fresh verified"):
            await runner.resume_verified(5)
        assert not run.done()

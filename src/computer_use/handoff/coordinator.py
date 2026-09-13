"""Same-session handoff with a conservative savings-page resume contract."""

import asyncio
from time import monotonic
from urllib.parse import urlsplit
from playwright.async_api import Error as BrowserError

from computer_use.handoff.capture import HumanCapture
from computer_use.schemas.intervention import Resolution
from computer_use.schemas.result import Diagnostic, Failure
from computer_use.surfaces.base import SurfaceError
from computer_use.observability.evidence import PersistenceError


class HandoffCoordinator:
    def __init__(self, engine, *, wait_timeout=900, max_handoffs=3):
        if not 1 <= wait_timeout <= 3600 or not 1 <= max_handoffs <= 5:
            raise ValueError("Invalid handoff bounds")
        self.engine = engine
        self.executor = engine.executor
        self.session = self.executor._session
        self.config = self.executor._config
        if self.config.target.product != "synthetic_bank":
            raise ValueError("Only the reviewed synthetic-bank handoff is implemented")
        self.contract = getattr(engine, "task", None) or engine.capability
        self.wait_timeout, self.max_handoffs = wait_timeout, max_handoffs
        self.capture = HumanCapture(self.executor)
        self.capture.on_failure = self._capture_failed
        self._lock = asyncio.Lock()
        self._decision = None
        self._wait_started = None
        self._count = 0
        self._failure = None
        self._resume_ticket = None
        self.notice = "Waiting for a blocked run"
        self.ready = asyncio.Event()
        engine.handoff = self

    def _capture_failed(self):
        if self._decision is not None and not self._decision.done():
            self._decision.set_exception(PersistenceError())

    def consume_resume(self, start):
        if self.executor.control.state != "AUTOMATION_RUNNING" or self._resume_ticket != (start, self.executor.session_id):
            raise ValueError("Resume requires a fresh verified operator handoff")
        self._resume_ticket = None

    def _human_request(self, request):
        if self.executor.control.state != "HUMAN_CONTROL" or self._decision is None or self._decision.done():
            return False
        if self.capture.failed:
            return False
        self.executor._policy.human_request(request, self.executor._inputs)
        return True

    def _event(self, name, *, evidence_ref=None, **details):
        self.executor.store.event(event=name, control_state=self.executor.control.state,
                                  evidence_ref=evidence_ref, details=details)

    async def status(self):
        record = self.engine.intervention
        return {"state": self.executor.control.state, "run_id": self.executor.run_id,
                "session_id": self.executor.session_id, "notice": self.notice,
                "goal": "Retrieve the requested member's savings balance and currency",
                "step_action": self.engine._last_step.action.action if self.engine._last_step else None,
                "intervention": record.model_dump(mode="json") if record else None,
                "human_events": self.capture.count,
                "result": {"status": self.engine.result.status} if self.engine.result else None}

    async def handle(self, engine, failure):
        self._count += 1
        if self._count > self.max_handoffs:
            await self.executor.transition("FAILED", "Handoff count exhausted")
            return await engine._finish(failure)
        self._failure = failure
        self._decision = asyncio.get_running_loop().create_future()
        self._wait_started = monotonic()
        deadline = getattr(engine, "_deadline", None)
        if deadline is not None and deadline.expired():
            deadline = None
        if deadline is not None:
            deadline.reschedule(None)
        await self.capture.install()
        await self.capture.mode("AWAITING_HUMAN")
        self.session._boundary.human_authorizer = self._human_request
        self.notice = "Paused: " + engine.intervention.context.state + ". Take control, resolve the bank page, then request resume."
        self._event("handoff_requested", intervention_id=failure.intervention_id)
        self.ready.set()
        try:
            action, start = await asyncio.wait_for(asyncio.shield(self._decision), self.wait_timeout)
        except TimeoutError:
            await self.command("cancel")
            action, start = "abort", None
            self.notice = "Operator deadline elapsed; run cancelled"
        finally:
            self.session._boundary.human_authorizer = None
        if action == "abort":
            result = Failure(**engine._run_context(), status="failure", code="cancelled",
                diagnostic=failure.diagnostic, intervention_id=failure.intervention_id)
            return await engine._finish(result)
        if deadline is not None:
            remaining = self.executor._started_at + self.config.runtime.run_timeout_seconds - monotonic()
            deadline.reschedule(asyncio.get_running_loop().time() + max(0.001, remaining))
        return await engine.resume_verified(start)

    def _account_path(self):
        return "/members/" + self.executor._inputs["member_id"] + "/accounts"

    async def _verify_resume(self):
        # A different permitted page is still the wrong place to resume this task.
        observation = await self.executor.inspect_runtime()
        if (observation.state != "ready" or observation.target.product != self.contract.target.product
                or observation.target.version not in self.contract.target.versions
                or urlsplit(self.session._page.url).path != self._account_path()):
            raise ValueError("Requested member accounts page is required")
        if not await self.executor.check_condition(self.contract.success_checkpoint):
            raise ValueError("Account owner checkpoint is not satisfied")
        if hasattr(self.engine, "candidates"):
            reads = [s for s in self.engine.candidates if s.action.action == "read"]
            start = 0
        else:
            steps = self.engine.capability.steps
            start = next(i for i, step in enumerate(steps) if step.action.action == "read")
            if any(step.action.action not in {"read", "verify", "wait"} for step in steps[start:]):
                raise ValueError("Resume cannot skip or repeat a mutation")
            reads = [s for s in steps[start:] if s.action.action == "read"]
        if {s.action.output for s in reads} != set(self.contract.outputs):
            raise ValueError("All outputs require fresh reads")
        for step in reads:
            if not (await self.executor.preview(step)).get("visible"):
                raise ValueError("An output target is absent")
        return start, reads[0].id

    async def command(self, command):
        try:
            async with asyncio.timeout(30):
                return await self._command(command)
        except PersistenceError:
            await self.session.close()
            self._capture_failed()
            raise
        except (BrowserError, SurfaceError, TimeoutError, asyncio.CancelledError) as error:
            # A failed/cancelled control command must never leave an unattended
            # RESUME_CHECK or a half-transferred session running.
            async with self._lock:
                await self.session.close()
                if self._decision is not None and not self._decision.done():
                    try:
                        await self.executor.transition("FAILED", "Operator command interrupted; session closed")
                        self._resolve("abort", None, verified=False)
                        self._decision.set_result(("abort", None))
                    except PersistenceError:
                        self._capture_failed()
                        raise
                self.notice = "Session closed; run cancelled safely"
            if isinstance(error, asyncio.CancelledError):
                raise
            return await self.status()

    async def _command(self, command):
        async with self._lock:
            if self._decision is None or self._decision.done():
                raise ValueError("No open intervention")
            if command == "focus":
                self.session.control.require_open()
                await self.session._page.bring_to_front()
                return await self.status()
            if command == "takeover":
                if self.executor.control.state != "AWAITING_HUMAN":
                    raise ValueError("Takeover requires a paused run")
                await self.executor.transition("HUMAN_CONTROL", "Operator accepted exclusive control")
                await self.capture.mode("HUMAN_CONTROL")
                await self.session._page.bring_to_front()
                self.notice = "You control the existing bank window. Resolve it, then request resume."
                return await self.status()
            if command not in {"resume", "cancel"}:
                raise ValueError("Unknown operator command")
            if command == "resume" and self.executor.control.state != "HUMAN_CONTROL":
                raise ValueError("Take control before requesting resume")
            try:
                await self.capture.mode("RESUME_CHECK")
                await self.capture.flush()
                if command == "cancel":
                    await self.executor.transition("FAILED", "Operator cancelled run")
                    self._resolve("abort", None, verified=False)
                    self._decision.set_result(("abort", None))
                    self.notice = "Cancelled; no further automation actions"
                    return await self.status()
                await self.executor.transition("RESUME_CHECK", "Operator returned control for verification")
                self.executor.exclude_operator_wait(monotonic() - self._wait_started)
                self._wait_started = monotonic()
                try:
                    start, step_id = await self._verify_resume()
                except (SurfaceError, ValueError):
                    await self.executor.transition("AWAITING_HUMAN", "Resume verification failed")
                    await self.capture.mode("AWAITING_HUMAN")
                    self.notice = "Resume rejected: the requested account page and outputs must be visible. Take control to correct the page."
                    self._event("resume_rejected", code="checkpoint_failed")
                    return await self.status()
                await self.executor.transition("AUTOMATION_RUNNING", "Requested account page and outputs verified")
                self._resolve("resume", step_id, verified=True)
                await self.capture.mode("AUTOMATION_RUNNING")
                self._resume_ticket = (start, self.executor.session_id)
                self._decision.set_result(("resume", start))
                self.notice = "Verified. Automation will reread outputs and check completion."
                return await self.status()
            except PersistenceError:
                await self.session.close()
                if not self._decision.done():
                    self._decision.set_exception(PersistenceError())
                raise

    def _resolve(self, action, step_id, *, verified):
        record = self.engine.intervention
        reference = self.executor.store.diagnostic("human_event", {"count": self.capture.count, "run_id": self.executor.run_id})
        resolution = Resolution(action=action, operator_id="local_operator", summary="Operator handoff " + action,
            human_actions_ref=reference, state_verified=verified, resume_step_id=step_id,
            verification=Diagnostic(step_id=record.step_id, expected="Requested account owner and all output targets visible",
                                    observed="Checkpoint and read targets verified") if verified else None)
        resolved = record.model_copy(update={"control": self.executor.control, "resolution": resolution})
        evidence_ref = self.executor.save_resolution(resolved)
        self._event("handoff_resolved", action=action, evidence_ref=evidence_ref)

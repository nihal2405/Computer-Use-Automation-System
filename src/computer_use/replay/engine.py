"""Deterministic replay. This module has no discovery or model-client imports."""

import asyncio
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from computer_use.capabilities.store import CapabilityStore
from computer_use.execution.executor import Executor
from computer_use.execution.targeting import bind_references
from computer_use.observability.evidence import PersistenceError
from computer_use.replay.recovery import RecoveryBudget, extract_value
from computer_use.safety.policy import Policy
from computer_use.safety.urls import split_url
from computer_use.schemas.action import action_adapter
from computer_use.schemas.capability import Capability, Step, TargetIdentity
from computer_use.schemas.intervention import Intervention
from computer_use.schemas.observation import Observation
from computer_use.schemas.result import BusinessOutcome, Diagnostic, Failure, Success
from computer_use.settings import Configuration, load_configuration
from computer_use.surfaces.base import SurfaceError


class ReplayRequestError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__("Replay request failed validation before browser startup")


_HARD_STATES = {
    "validation_error": "invalid_input", "permission_denied": "permission_denied",
    "session_expired": "session_expired", "application_error": "application_error",
    "unexpected_dialog": "unknown_state", "unknown": "unknown_state",
}
_RESULT_CODES = set(Failure.model_fields["code"].annotation.__args__)


class ReplayEngine:
    """One run per engine. Its context owns browser lifetime, including a paused run."""

    def __init__(self, *, capability, configuration: Configuration, project_root: Path, inputs):
        try:
            self.capability = Capability.model_validate_json(Capability.model_validate(capability).model_dump_json())
            self._configuration = Configuration.model_validate_json(configuration.model_dump_json())
            self._inputs = self.capability.validate_inputs(inputs)
        except (ValidationError, ValueError, TypeError):
            raise ReplayRequestError("invalid_input") from None
        target = self._configuration.target
        if (self.capability.target.product != target.product or self.capability.target.surface != target.surface
                or not set(self.capability.target.versions).intersection(target.supported_versions)):
            raise ReplayRequestError("incompatible_target")
        policy = Policy(self._configuration.policy)
        try:
            policy.inputs(self._inputs)
            origin, entry_path = split_url(target.entry_url)
            if self.capability.steps[0].action.action != "navigate" or self.capability.steps[0].action.path != entry_path:
                raise ReplayRequestError("invalid_input")
            for step in self.capability.steps:
                bound = action_adapter.validate_python(bind_references(step.action, self._inputs))
                policy.authorize(bound, step.operation, self._inputs, target.entry_url, origin)
                for condition in (step.precondition, step.postcondition):
                    if condition is not None:
                        bound = action_adapter.validate_python({"action": "verify", "condition": bind_references(condition, self._inputs)})
                        policy.authorize(bound, step.operation, self._inputs, target.entry_url, origin)
            policy.condition_operation(self.capability.success_checkpoint, self._inputs)
            for rule in self.capability.business_outcomes:
                policy.condition_operation(rule.when, self._inputs)
            for rule in self.capability.recovery_rules:
                policy.condition_operation(rule.when, self._inputs)
                policy.condition_operation(rule.until, self._inputs, action="wait")
        except SurfaceError as error:
            raise ReplayRequestError(error.code) from None
        self._policy = policy
        self.executor = Executor(configuration=self._configuration, project_root=project_root, mode="replay", inputs=self._inputs)
        self._recovery = RecoveryBudget(self._configuration.runtime.max_retries)
        self.intervention = None
        self.result = None
        self._ran = False
        self._last_step = None
        self.handoff = None

    @classmethod
    def from_project(cls, project_root: Path, *, artifact: Path, inputs):
        return cls(capability=CapabilityStore.load(artifact), configuration=load_configuration(project_root),
                   project_root=project_root, inputs=inputs)

    async def __aenter__(self):
        await self.executor.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self.executor.__aexit__(*args)

    def _run_context(self):
        return dict(schema_version="1.0", run_id=self.executor.run_id, session_id=self.executor.session_id,
                    mode="replay", capability_id=self.capability.id, capability_version=self.capability.capability_version)

    async def _inspect(self):
        observation = await self.executor.inspect_runtime()
        try:
            self.capability.validate_target(observation.target)
        except ValueError:
            raise SurfaceError("incompatible_target", "Artifact-compatible live target", "Visible target version is incompatible") from None
        return observation

    async def _finish(self, result):
        self.capability.validate_result(result)
        event = {"success": "run_completed", "failure": "run_failed", "business_outcome": "business_outcome"}[result.status]
        self.executor.store.event(event=event, step_id=self._last_step.id if self._last_step else None,
            control_state=self.executor.control.state, details=result.model_dump(mode="json"))
        self.executor.store.diagnostic("result_diagnostic", result)
        self.result = result
        return result

    async def _fail(self, step, code, *, expected="A verified workflow outcome", observed="Replay cannot safely continue", diagnostic=None):
        code = code if code in _RESULT_CODES else "unknown_state"
        if diagnostic is None:
            outcome = await self.executor.report_failure(step, code, expected, observed)
            diagnostic = outcome.diagnostic
        record_id = None
        if code not in {"invalid_input", "cancelled", "persistence_failed"}:
            try:
                context = await self._inspect()
            except SurfaceError:
                context = Observation(schema_version="1.0", run_id=self.executor.run_id, session_id=self.executor.session_id,
                    sequence=0, target=TargetIdentity(product=self._configuration.target.product,
                        version=self._configuration.target.supported_versions[0], surface="browser"),
                    location="unavailable", summary="Current UI observation unavailable", controls=[], state="unknown")
            try:
                await self.executor.transition("AWAITING_HUMAN", "Replay requires review before further actions")
            except (SurfaceError, ValueError):  # Closed or externally controlled sessions cannot offer this takeover.
                pass
            else:
                record_id = str(uuid4())
                reason = code if code in {"recovery_exhausted", "no_progress", "step_limit", "timeout", "session_expired", "permission_denied"} else ("policy_blocked" if code == "policy_denied" else "unknown_state")
                record = Intervention(schema_version="1.0", id=record_id, run_id=self.executor.run_id,
                    session_id=self.executor.session_id, goal=self.capability.description,
                    capability_id=self.capability.id, capability_version=self.capability.capability_version,
                    step_id=step.id if step else None, reason=reason, diagnostic=diagnostic,
                    context=context, control=self.executor.control)
                self.intervention = self.executor.save_intervention(record)
        else:
            try:
                await self.executor.transition("FAILED", "Replay failed")
            except (SurfaceError, ValueError):
                pass
        result = Failure(**self._run_context(), status="failure", code=code,
            diagnostic=diagnostic, intervention_id=record_id)
        if self.handoff is not None and record_id:
            return await self.handoff.handle(self, result)
        return await self._finish(result)

    async def _recover(self, rule, step):
        operation = self._policy.condition_operation(rule.until, self._inputs, action="wait")
        wait_step = Step(id=step.id, operation=operation, action={"action": "wait", "condition": rule.until,
                         "timeout_ms": rule.timeout_ms}, timeout_ms=rule.timeout_ms)
        for retry in range(self._recovery.remaining(rule)):
            self._recovery.consume(rule)
            self.executor.store.event(event="recovery_started", step_id=step.id, action="wait", retry=retry,
                control_state=self.executor.control.state, details={"code": rule.code})
            outcome = await self.executor.execute_step(wait_step, retry=retry)
            if outcome.status == "success":
                return None
            if outcome.code != "timeout":
                return await self._fail(step, outcome.code, diagnostic=outcome.diagnostic)
        return await self._fail(step, "recovery_exhausted", expected="Recovery condition within the bounded wait budget",
                                observed="Allowed wait attempts exhausted; original action was not repeated")

    async def _gate(self, step):
        while True:
            observation = await self._inspect()
            if observation.state in _HARD_STATES:
                return await self._fail(step, _HARD_STATES[observation.state], observed=observation.state)
            for rule in self.capability.business_outcomes:
                if await self.executor.check_condition(rule.when, step_id=step.id):
                    await self.executor.transition("COMPLETED", "Expected business outcome observed")
                    return await self._finish(BusinessOutcome(**self._run_context(), status="business_outcome",
                        code=rule.code, step_id=step.id, summary="Configured business outcome observed in the UI"))
            recovering = False
            for rule in self.capability.recovery_rules:
                if await self.executor.check_condition(rule.when, step_id=step.id):
                    failure = await self._recover(rule, step)
                    if failure:
                        return failure
                    recovering = True
                    break
            if recovering:
                continue  # The same rule shares one run-wide budget; no unbounded reset.
            if observation.state != "ready":
                # A delayed page can finish between the observation and condition
                # probes. Recheck readiness before declaring that transient unknown.
                if (await self._inspect()).state == "ready":
                    continue
                return await self._fail(step, "unknown_state", observed="State has no matching approved outcome or recovery rule")
            return None

    async def run(self):
        if self._ran:
            raise RuntimeError("A replay engine may execute only once")
        if self.executor.store is None:
            raise RuntimeError("Replay engine must be entered before running")
        self._ran = True
        return await self._run_steps(0)

    async def resume_verified(self, start):
        if self.handoff is None:
            raise ValueError("Resume requires a handoff coordinator")
        self.handoff.consume_resume(start)
        return await self._run_steps(start)

    async def _run_steps(self, start):
        outputs = {}
        try:
            for index, step in enumerate(self.capability.steps):
                if index < start:
                    continue
                self._last_step = step
                if index:
                    terminal = await self._gate(step)
                    if terminal:
                        return terminal
                outcome = await self.executor.execute_step(step)
                if outcome.status == "failure":
                    # A navigation may have reached a 401/403/503 page before its
                    # postcondition failed. Preserve the real application outcome.
                    code = outcome.code
                    if code == "checkpoint_failed":
                        state = (await self._inspect()).state
                        code = _HARD_STATES.get(state, code)
                    return await self._fail(step, code, diagnostic=outcome.diagnostic)
                if step.action.action == "read":
                    try:
                        outputs[step.action.output] = extract_value(self.capability.outputs[step.action.output], outcome.output)
                    except ValueError:
                        return await self._fail(step, "invalid_output", expected="Visible output matching its declared type",
                                                observed="Read value does not satisfy the output contract")
            terminal = await self._gate(self._last_step)
            if terminal:
                return terminal
            checkpoint = Step(id=self._last_step.id,
                operation=self._policy.condition_operation(self.capability.success_checkpoint, self._inputs),
                action={"action": "verify", "condition": self.capability.success_checkpoint})
            outcome = await self.executor.execute_step(checkpoint)
            if outcome.status == "failure":
                return await self._fail(self._last_step, outcome.code, diagnostic=outcome.diagnostic)
            try:
                self.capability.validate_outputs(outputs)
            except ValueError:
                return await self._fail(self._last_step, "invalid_output", observed="Final outputs do not satisfy the declared contract")
            await self.executor.transition("COMPLETED", "Final checkpoint and outputs validated")
            return await self._finish(Success(**self._run_context(), status="success", checkpoint_verified=True, outputs=outputs))
        except SurfaceError as error:
            try:
                return await self._fail(self._last_step, error.code, expected=error.expected, observed=error.observed)
            except PersistenceError:
                return await self._persistence_failure()
        except PersistenceError:
            return await self._persistence_failure()
        except asyncio.CancelledError:
            await self.executor.__aexit__()
            raise

    async def _persistence_failure(self):
        await self.executor.__aexit__()
        self.result = Failure(**self._run_context(), status="failure", code="persistence_failed",
            diagnostic=Diagnostic(step_id=self._last_step.id if self._last_step else None,
                                  expected="Sanitized audit evidence stored", observed="Persistence failed; browser closed"))
        return self.result

"""Bounded live observe → decide → act loop, independent of development fixtures."""

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from computer_use.capabilities.compiler import compile_capability
from computer_use.capabilities.store import CapabilityStore
from computer_use.discovery.contracts import Decision, DiscoveryTask
from computer_use.discovery.model_client import ModelError, OpenAIModel
from computer_use.discovery.recorder import Recorder
from computer_use.execution.executor import Executor
from computer_use.observability.evidence import PersistenceError
from computer_use.replay.recovery import RecoveryBudget, extract_value
from computer_use.safety.policy import Policy, canonical
from computer_use.safety.urls import split_url
from computer_use.schemas.capability import Step, TargetIdentity
from computer_use.schemas.common import check_values
from computer_use.schemas.intervention import Intervention
from computer_use.schemas.observation import Observation
from computer_use.schemas.result import BusinessOutcome, Diagnostic, Failure, Success
from computer_use.settings import Configuration, load_configuration
from computer_use.surfaces.base import SurfaceError

HARD_STATES = {
    "validation_error": "invalid_input",
    "permission_denied": "permission_denied",
    "session_expired": "session_expired",
    "application_error": "application_error",
    "unexpected_dialog": "unknown_state",
    "unknown": "unknown_state",
}


class DiscoveryAgent:
    def __init__(self, *, task, configuration, project_root, inputs, model):
        self.task = DiscoveryTask.model_validate_json(
            DiscoveryTask.model_validate(task).model_dump_json()
        )
        self.config = Configuration.model_validate_json(configuration.model_dump_json())
        check_values(self.task.inputs, inputs)
        self.inputs = dict(inputs)
        self.project_root = Path(project_root)
        target = self.config.target
        if (
            target.product != self.task.target.product
            or target.surface != self.task.target.surface
            or not set(target.supported_versions).intersection(self.task.target.versions)
        ):
            raise ValueError("Incompatible discovery target")
        self.policy = Policy(self.config.policy)
        self.policy.inputs(self.inputs)
        for condition in [
            self.task.success_checkpoint,
            *[r.when for r in self.task.business_outcomes],
            *[r.when for r in self.task.recovery_rules],
        ]:
            self.policy.condition_operation(condition, self.inputs)
        for rule in self.task.recovery_rules:
            self.policy.condition_operation(rule.until, self.inputs, action="wait")
        self.candidates = self._candidates()
        self.recorder = Recorder(self.candidates, self.inputs)
        self.executor = Executor(
            configuration=self.config,
            project_root=project_root,
            mode="discovery",
            inputs=self.inputs,
        )
        self.model = model
        self.recovery = RecoveryBudget(self.config.runtime.max_retries)
        self.outputs = {}
        self.artifact_path = self.capability = self.intervention = self.result = None
        self._last_step = None
        self._ran = False
        self._context = None
        self.provider_failure = None
        self.handoff = None
        self.human_assisted = False

    @classmethod
    def from_project(cls, root, *, task_path, inputs, model, configuration=None, goal=None):
        path = Path(task_path)
        if path.stat().st_size > 131072:
            raise ValueError("Task is too large")
        task = DiscoveryTask.model_validate_json(path.read_text())
        if goal is not None:
            task = DiscoveryTask.model_validate({**task.model_dump(), "goal": goal})
        return cls(
            task=task,
            configuration=configuration or load_configuration(root),
            project_root=root,
            inputs=inputs,
            model=model,
        )

    def _candidates(self):
        import re

        _, entry = split_url(self.config.target.entry_url)
        candidates = []
        for rule in self.config.policy.rules:
            action = rule.model_dump(exclude_none=True)
            action.pop("operation")
            if rule.action == "navigate":
                if not re.fullmatch(rule.path, entry):
                    continue
                action["path"] = entry
            if rule.action == "read":
                names = [
                    name
                    for name, target in self.task.output_targets.items()
                    if canonical(target.model_dump()) == canonical(rule.target.model_dump())
                ]
                if len(names) != 1:
                    continue
                action["output"] = names[0]
            if rule.action == "wait":
                action["timeout_ms"] = self.config.runtime.step_timeout_seconds * 1000
            candidates.append(
                Step(id=f"candidate_{len(candidates)}", operation=rule.operation, action=action)
            )
        if {s.action.output for s in candidates if s.action.action == "read"} != set(
            self.task.outputs
        ):
            raise ValueError("Output targets must have reviewed read permissions")
        if not any(s.action.action == "navigate" for s in candidates):
            raise ValueError("Discovery requires an approved entry navigation")
        # Policy order is not a hidden workflow supplied to the model.
        return sorted(
            candidates, key=lambda step: json.dumps(step.action.model_dump(), sort_keys=True)
        )

    async def __aenter__(self):
        try:
            await self.executor.__aenter__()
            return self
        except BaseException:
            await self.model.close()
            raise

    async def __aexit__(self, *args):
        try:
            await self.executor.__aexit__(*args)
        finally:
            await self.model.close()

    def _run_context(self):
        return dict(
            schema_version="1.0",
            run_id=self.executor.run_id,
            session_id=self.executor.session_id,
            mode="discovery",
        )

    def _event(self, event, **details):
        self.executor.store.event(
            event=event,
            step_id=self._last_step.id if self._last_step else None,
            control_state=self.executor.control.state,
            details=details,
        )

    async def _finish(self, result):
        self._event(
            {
                "success": "run_completed",
                "failure": "run_failed",
                "business_outcome": "business_outcome",
            }[result.status],
            **result.model_dump(mode="json"),
        )
        self.executor.store.diagnostic("result_diagnostic", result)
        self.result = result
        return result

    async def _stop(self, code, diagnostic=None):
        if code not in Failure.model_fields["code"].annotation.__args__:
            code = "unknown_state"
        if diagnostic is None:
            failed = await self.executor.report_failure(
                self._last_step,
                code,
                "Verified progress within approved discovery limits",
                "Discovery stopped: " + code,
            )
            diagnostic = failed.diagnostic
        intervention_id = None
        if code != "invalid_input":
            context = self._context or Observation(
                schema_version="1.0",
                run_id=self.executor.run_id,
                session_id=self.executor.session_id,
                sequence=0,
                target=TargetIdentity(
                    product=self.config.target.product,
                    version=self.config.target.supported_versions[0],
                    surface="browser",
                ),
                location="unavailable",
                summary="UI unavailable",
                controls=[],
                state="unknown",
            )
            try:
                await self.executor.transition("AWAITING_HUMAN", "Discovery requires review")
            except (SurfaceError, ValueError):
                pass
            else:
                intervention_id = str(uuid4())
                reason = (
                    code
                    if code
                    in {
                        "timeout",
                        "no_progress",
                        "step_limit",
                        "recovery_exhausted",
                        "permission_denied",
                        "session_expired",
                    }
                    else ("policy_blocked" if code == "policy_denied" else "unknown_state")
                )
                self.intervention = self.executor.save_intervention(
                    Intervention(
                        schema_version="1.0",
                        id=intervention_id,
                        **{
                            k: v
                            for k, v in self._run_context().items()
                            if k in {"run_id", "session_id"}
                        },
                        goal=self.task.goal,
                        step_id=diagnostic.step_id,
                        reason=reason,
                        diagnostic=diagnostic,
                        context=context,
                        control=self.executor.control,
                    )
                )
        else:
            await self.executor.transition("FAILED", "Invalid input")
        result = Failure(
            **self._run_context(),
            status="failure",
            code=code,
            diagnostic=diagnostic,
            intervention_id=intervention_id,
        )
        if self.handoff is not None and intervention_id:
            return await self.handoff.handle(self, result)
        return await self._finish(result)

    async def resume_verified(self, start):
        """Complete by fresh UI reads after a verified handoff; do not invent a capability."""
        if self.handoff is None:
            raise ValueError("Resume requires a handoff coordinator")
        self.handoff.consume_resume(start)
        self.human_assisted = True
        self.outputs = {}
        for step in self.candidates:
            if step.action.action != "read":
                continue
            self._last_step = step
            outcome = await self.executor.execute_step(step)
            if outcome.status != "success":
                return await self._stop(outcome.code, outcome.diagnostic)
            try:
                self.outputs[step.action.output] = extract_value(
                    self.task.outputs[step.action.output], outcome.output
                )
            except ValueError:
                return await self._stop("invalid_output")
        terminal = await self._gate()
        if terminal:
            return terminal
        checkpoint = Step(
            id="completion_check",
            operation=self.policy.condition_operation(self.task.success_checkpoint, self.inputs),
            action={"action": "verify", "condition": self.task.success_checkpoint},
        )
        self._last_step = checkpoint
        outcome = await self.executor.execute_step(checkpoint)
        if outcome.status != "success":
            return await self._stop(outcome.code, outcome.diagnostic)
        check_values(self.task.outputs, self.outputs)
        await self.executor.transition("COMPLETED", "Human-assisted result verified")
        return await self._finish(
            Success(
                **self._run_context(),
                status="success",
                checkpoint_verified=True,
                outputs=self.outputs,
            )
        )

    async def _gate(self):
        while True:
            self._context = await self.executor.inspect_runtime()
            if self._context.target.version not in self.task.target.versions:
                return await self._stop("incompatible_target")
            state = self._context.state
            if state in HARD_STATES:
                return await self._stop(HARD_STATES[state])
            for rule in self.task.business_outcomes:
                if await self.executor.check_condition(rule.when):
                    await self.executor.transition("COMPLETED", "Business outcome verified")
                    return await self._finish(
                        BusinessOutcome(
                            **self._run_context(),
                            status="business_outcome",
                            code=rule.code,
                            step_id=self._last_step.id,
                            summary="Declared business outcome observed",
                        )
                    )
            recovered = False
            for rule in self.task.recovery_rules:
                if not await self.executor.check_condition(rule.when):
                    continue
                operation = self.policy.condition_operation(rule.until, self.inputs, action="wait")
                step = Step(
                    id=f"recovery_{len(self.recorder.steps)}",
                    operation=operation,
                    action={
                        "action": "wait",
                        "condition": rule.until,
                        "timeout_ms": rule.timeout_ms,
                    },
                    timeout_ms=rule.timeout_ms,
                )
                for retry in range(self.recovery.remaining(rule)):
                    self.recovery.consume(rule)
                    self._event("recovery_started", code=rule.code, attempt=retry)
                    self._last_step = step
                    outcome = await self.executor.execute_step(step, retry=retry)
                    if outcome.status == "success":
                        recovered = True
                        break
                    if outcome.code != "timeout":
                        return await self._stop(outcome.code, outcome.diagnostic)
                if not recovered:
                    return await self._stop("recovery_exhausted")
                break
            if recovered:
                continue
            if state != "ready":
                if (await self.executor.inspect_runtime()).state == "ready":
                    continue
                return await self._stop("unknown_state")
            return None

    async def _observation(self):
        actions = []
        for step in self.candidates:
            preview = await self.executor.preview(step)
            actions.append(
                {
                    "operation": step.operation,
                    "action": step.action.model_dump(mode="json"),
                    **preview,
                }
            )
        return {
            "state": self._context.state,
            "permitted_actions": actions,
            "collected_outputs": sorted(self.outputs),
        }

    async def _complete(self):
        try:
            check_values(self.task.outputs, self.outputs)
        except ValueError:
            return await self._stop("checkpoint_failed")
        checkpoint = Step(
            id="completion_check",
            operation=self.policy.condition_operation(self.task.success_checkpoint, self.inputs),
            action={"action": "verify", "condition": self.task.success_checkpoint},
        )
        self._last_step = checkpoint
        checked = await self.executor.execute_step(checkpoint)
        if checked.status != "success":
            return await self._stop(checked.code, checked.diagnostic)
        capability = compile_capability(
            self.task,
            self.recorder,
            run_id=self.executor.run_id,
            identity=self._context.target,
            outputs=self.outputs,
            checkpoint_verified=True,
            live_provider=type(self.model) is OpenAIModel,
        )
        # Run the same compatibility and policy preflight that replay will perform.
        from computer_use.replay.engine import ReplayEngine

        ReplayEngine(
            capability=capability,
            configuration=self.config,
            project_root=self.project_root,
            inputs=self.inputs,
        )
        self.artifact_path = self.executor.artifacts.save(capability)
        self.capability = CapabilityStore.load(self.artifact_path)
        self._event(
            "artifact_created",
            capability_id=self.capability.id,
            capability_version=self.capability.capability_version,
            artifact_sha256=hashlib.sha256(self.artifact_path.read_bytes()).hexdigest(),
        )
        await self.executor.transition("COMPLETED", "Checkpoint verified and capability stored")
        return await self._finish(
            Success(
                **self._run_context(),
                capability_id=self.capability.id,
                capability_version=self.capability.capability_version,
                status="success",
                checkpoint_verified=True,
                outputs=self.outputs,
            )
        )

    async def _loop(self):
        bootstrap = next(s for s in self.candidates if s.action.action == "navigate")
        self._last_step = bootstrap.model_copy(update={"id": "entry_navigation"})
        outcome = await self.executor.execute_step(self._last_step)
        if outcome.status != "success":
            return await self._stop(outcome.code, outcome.diagnostic)
        self.recorder.append(self._last_step, outcome)
        visits = {}
        invalid = 0
        feedback = None
        for iteration in range(self.config.runtime.max_steps):
            terminal = await self._gate()
            if terminal:
                return terminal
            observation = await self._observation()
            fingerprint = json.dumps(observation, sort_keys=True)
            visits[fingerprint] = visits.get(fingerprint, 0) + 1
            if visits[fingerprint] > self.config.runtime.max_no_progress_steps:
                return await self._stop("no_progress")
            context = {
                "goal": self.task.goal,
                "input_references": [f"inputs.{k}" for k in self.task.inputs],
                "outputs": {k: v.model_dump() for k, v in self.task.outputs.items()},
                "success_checkpoint": self.task.success_checkpoint.model_dump(),
                "observation": observation,
                "feedback": feedback,
            }
            self._event("model_requested", observation=context)
            try:
                reply = await self.model.decide(context)
                decision = Decision.model_validate(reply.decision)
            except ModelError as error:
                if error.code != "invalid_model_response":
                    self.provider_failure = {
                        "status": error.provider_status,
                        "reason": error.provider_reason,
                    }
                    self._event("model_rejected", code=error.code, **self.provider_failure)
                    return await self._stop(error.code)
                invalid += 1
                self._event("model_rejected", code="invalid_model_response")
                if invalid > self.config.runtime.max_retries:
                    return await self._stop("invalid_model_response")
                feedback = "invalid_model_response"
                continue
            self._event(
                "model_response",
                response_id=reply.response_id,
                model=reply.model,
                requested_step=decision,
            )
            self.recorder.model_responses.append(reply.response_id)
            invalid = 0
            if decision.command == "intervene":
                return await self._stop("unknown_state")
            if decision.command == "complete":
                return await self._complete()
            try:
                step = self.recorder.normalize(decision.step)
            except ValueError:
                return await self._stop("invalid_model_response")
            self._last_step = step
            outcome = await self.executor.execute_step(step, model_explanation=decision.explanation)
            if outcome.status != "success":
                return await self._stop(outcome.code, outcome.diagnostic)
            self.recorder.append(step, outcome)
            if step.action.action == "read":
                try:
                    self.outputs[step.action.output] = extract_value(
                        self.task.outputs[step.action.output], outcome.output
                    )
                except ValueError:
                    return await self._stop("invalid_output")
                if set(self.outputs) == set(self.task.outputs):
                    # Completion is an executable contract, not another model opinion.
                    terminal = await self._gate()
                    return terminal if terminal else await self._complete()
            feedback = {"action": step.action.action, "status": "success"}
        return await self._stop("step_limit")

    async def run(self):
        if self._ran or self.executor.store is None:
            raise ValueError("Enter a new discovery context before running once")
        self._ran = True
        try:
            try:
                async with asyncio.timeout(self.config.runtime.run_timeout_seconds) as deadline:
                    self._deadline = deadline
                    return await self._loop()
            except TimeoutError:
                return await self._stop("timeout")
            except SurfaceError as error:
                return await self._stop(error.code)
        except PersistenceError:
            await self.executor.__aexit__()
            self.result = Failure(
                **self._run_context(),
                status="failure",
                code="persistence_failed",
                diagnostic=Diagnostic(
                    step_id=self._last_step.id if self._last_step else None,
                    expected="Sanitized evidence stored",
                    observed="Persistence failed; browser closed",
                ),
            )
            return self.result
        except asyncio.CancelledError:
            await self.executor.__aexit__()
            raise

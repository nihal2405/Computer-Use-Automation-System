"""Policy, ownership, deadlines, and diagnostics for every discovery or replay step."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError

from computer_use.capabilities.store import CapabilityStore
from computer_use.observability.evidence import EvidenceStore, PersistenceError
from computer_use.safety.policy import Policy
from computer_use.safety.redaction import Redactor
from computer_use.safety.urls import split_url
from computer_use.schemas.action import Condition
from computer_use.schemas.capability import Step, TargetIdentity
from computer_use.schemas.intervention import Intervention
from computer_use.schemas.observation import Observation
from computer_use.schemas.result import Diagnostic
from computer_use.sessions.manager import BrowserSession
from computer_use.settings import Configuration, load_configuration
from computer_use.surfaces.base import SurfaceError


@dataclass(frozen=True)
class StepOutcome:
    status: Literal["success", "failure"]
    step_id: str | None
    output: str | None = None  # Authorized caller result only; never persisted verbatim.
    code: str | None = None
    diagnostic: Diagnostic | None = None


class Executor:
    def __init__(self, *, configuration: Configuration, project_root: Path, mode, inputs):
        if mode not in {"discovery", "replay"}:
            raise ValueError("Mode must be discovery or replay")
        self._config = Configuration.model_validate_json(configuration.model_dump_json())
        self._policy = Policy(self._config.policy)
        self._inputs = self._policy.inputs(dict(inputs))
        self._redactor = Redactor(
            self._policy.vocabulary()
            | {self._config.target.product, *self._config.target.supported_versions}
        )
        self._redactor.register(self._inputs.values())
        self.run_id = str(uuid4())
        self.mode = mode
        root = project_root.resolve()
        self._output_root = (root / self._config.runtime.run_directory).resolve()
        if not self._output_root.is_relative_to(root):
            raise ValueError("Output directory escapes the project")
        artifact_root = (root / self._config.runtime.artifact_directory).resolve()
        if not artifact_root.is_relative_to(root):
            raise ValueError("Artifact directory escapes the project")
        self.artifacts = CapabilityStore(artifact_root, self._redactor)
        origin, _ = split_url(self._config.target.entry_url)
        self._session = BrowserSession(
            base_url=origin,
            target=TargetIdentity(
                product=self._config.target.product,
                version=self._config.target.supported_versions[0],
                surface="browser",
            ),
            run_id=self.run_id,
            headless=self._config.runtime.browser.headless,
            timeout_ms=self._config.runtime.step_timeout_seconds * 1000,
            policy=self._policy,
            versions=self._config.target.supported_versions,
        )
        self._lock = asyncio.Lock()
        self._steps = 0
        self._last_wait = None
        self._started_at = None
        self.store = None

    @classmethod
    def from_project(cls, project_root: Path, *, mode, inputs):
        return cls(
            configuration=load_configuration(project_root),
            project_root=project_root,
            mode=mode,
            inputs=inputs,
        )

    @property
    def session_id(self):
        return self._session.session_id

    @property
    def control(self):
        return self._session.control.snapshot

    async def __aenter__(self):
        if self._started_at is not None:
            raise ValueError("Executor cannot be restarted")
        try:
            self.store = EvidenceStore(
                self._output_root,
                self._redactor,
                run_id=self.run_id,
                session_id=self.session_id,
                mode=self.mode,
            )
            self._session.control.on_transition = self._control_event
            await self._session.start()
            self._started_at = monotonic()
            return self
        except BaseException:
            await self._session.close()
            raise

    async def __aexit__(self, *_):
        await self._session.close()

    def _control_event(self, transition):
        self.store.event(
            event="control_change",
            control_state=transition.after.state,
            details={
                "before": transition.before.state,
                "after": transition.after.state,
                "reason": transition.reason,
            },
        )

    async def transition(self, state, reason):
        async with self._lock:
            try:
                return await self._session.control.transition(state, reason)
            except PersistenceError:
                await self._session.close()
                raise

    def _budget(self, step_deadline):
        remaining = (
            min(step_deadline, self._started_at + self._config.runtime.run_timeout_seconds)
            - monotonic()
        )
        if remaining <= 0:
            raise SurfaceError("timeout", "Execution within configured limits", "Deadline elapsed")
        return max(1, min(60_000, int(remaining * 1000)))

    async def execute_step(self, step, *, retry=0, model_explanation=None):
        """Run one step; retry requests are permitted only for the last timed-out wait."""
        if self.store is None or self._started_at is None:
            raise ValueError("Executor must be started")
        async with self._lock:
            validated = None
            checkpoint = "not_checked"
            try:
                self._session.surface.policy_decision = "not_checked"
                try:
                    validated = Step.model_validate(step)
                except (ValidationError, ValueError, TypeError):
                    raise SurfaceError(
                        "invalid_input", "A validated step", "Invalid step contract"
                    ) from None
                if type(retry) is not int or not 0 <= retry <= self._config.runtime.max_retries:
                    raise SurfaceError("invalid_input", "A bounded retry count", "Invalid retry")
                if retry and (
                    validated.action.action != "wait"
                    or self._last_wait != (validated.model_dump_json(), retry - 1)
                ):
                    raise SurfaceError(
                        "policy_denied", "Retry only a timed-out wait", "Unsafe or unrelated retry"
                    )
                if self._steps >= self._config.runtime.max_steps:
                    raise SurfaceError(
                        "step_limit", "Steps within the configured limit", "Step limit reached"
                    )
                self._steps += 1
                self._last_wait = None
                deadline = (
                    monotonic()
                    + min(validated.timeout_ms, self._config.runtime.step_timeout_seconds * 1000)
                    / 1000
                )
                self._budget(deadline)
                self.store.event(
                    event="started",
                    step_id=validated.id,
                    action=validated.action.action,
                    retry=retry,
                    control_state=self.control.state,
                    details={
                        "action_record": validated.action,
                        "inputs": self._inputs,
                        "model_explanation": model_explanation,
                    },
                )
                if validated.precondition is not None:
                    await self._session.surface.execute(
                        {"action": "verify", "condition": validated.precondition},
                        self._inputs,
                        timeout_ms=self._budget(deadline),
                        operation=validated.operation,
                    )
                    checkpoint = "passed"
                output = await self._session.surface.execute(
                    validated.action,
                    self._inputs,
                    timeout_ms=self._budget(deadline),
                    operation=validated.operation,
                )
                if validated.postcondition is not None:
                    await self._session.surface.execute(
                        {"action": "verify", "condition": validated.postcondition},
                        self._inputs,
                        timeout_ms=self._budget(deadline),
                        operation=validated.operation,
                    )
                    checkpoint = "passed"
                if validated.action.action == "verify":
                    checkpoint = "passed"
                if output is not None:
                    self._redactor.register([output])
                self.store.event(
                    event="completed",
                    step_id=validated.id,
                    action=validated.action.action,
                    policy_decision="allowed",
                    checkpoint=checkpoint,
                    retry=retry,
                    control_state=self.control.state,
                    details={"output": output},
                )
                return StepOutcome(status="success", step_id=validated.id, output=output)
            except SurfaceError as error:
                if (
                    validated is not None
                    and validated.action.action == "wait"
                    and error.code == "timeout"
                ):
                    self._last_wait = (validated.model_dump_json(), retry)
                if error.code == "checkpoint_failed":
                    checkpoint = "failed"
                return await self._failure(
                    validated,
                    error,
                    retry if type(retry) is int and 0 <= retry <= 3 else 0,
                    checkpoint,
                )
            except PersistenceError:
                await self._session.close()
                raise
            except asyncio.CancelledError:
                await self._failure(
                    validated,
                    SurfaceError(
                        "cancelled", "An uninterrupted operation", "Caller cancelled execution"
                    ),
                    0,
                    checkpoint,
                )
                raise

    async def _failure(self, step, error, retry, checkpoint):
        try:
            try:
                snapshot = await self._session.surface.failure_snapshot()
            except SurfaceError:
                snapshot = {"unavailable": True}
            reference = self.store.diagnostic("dom_structure", snapshot)
            self.store.event(
                event="failure",
                step_id=step.id if step else None,
                action=step.action.action if step else None,
                retry=retry,
                checkpoint=checkpoint,
                policy_decision="denied"
                if error.code == "policy_denied"
                else self._session._surface.policy_decision,
                control_state=self.control.state,
                evidence_ref=reference,
                details={
                    "code": error.code,
                    "expected": error.expected,
                    "observed": error.observed,
                },
            )
            return StepOutcome(
                status="failure",
                step_id=step.id if step else None,
                code=error.code,
                diagnostic=Diagnostic(
                    step_id=step.id if step else None,
                    expected=error.expected,
                    observed=error.observed,
                    evidence_ref=reference,
                ),
            )
        except PersistenceError:
            await self._session.close()
            raise

    async def observe(self):
        async with self._lock:
            try:
                deadline = monotonic() + self._config.runtime.step_timeout_seconds
                observation = await self._session.surface.observe(timeout_ms=self._budget(deadline))
                self.store.event(
                    event="observation",
                    control_state=self.control.state,
                    details={"observation": observation},
                )
                return self._redactor.sanitize(observation)
            except SurfaceError as error:
                await self._failure(None, error, 0, "not_checked")
                raise
            except PersistenceError:
                await self._session.close()
                raise

    def _safe_observation(self, observation):
        data = self._redactor.sanitize(observation)
        data.update(
            schema_version="1.0",
            run_id=self.run_id,
            session_id=self.session_id,
            sequence=observation.sequence,
            target=observation.target.model_dump(),
            state=observation.state,
        )
        return Observation.model_validate(data)

    async def inspect_runtime(self) -> Observation:
        """Typed, sanitized state for deterministic controllers and intervention records."""
        async with self._lock:
            try:
                deadline = monotonic() + self._config.runtime.step_timeout_seconds
                raw = await self._session.surface.observe(timeout_ms=self._budget(deadline))
                safe = self._safe_observation(raw)
                self.store.event(
                    event="observation",
                    control_state=self.control.state,
                    details={"observation": safe},
                )
                return safe
            except PersistenceError:
                await self._session.close()
                raise

    async def check_condition(self, condition: Condition, *, step_id=None) -> bool:
        async with self._lock:
            try:
                operation = self._policy.condition_operation(condition, self._inputs)
                deadline = monotonic() + self._config.runtime.step_timeout_seconds
                result = await self._session.surface.evaluate(
                    condition, self._inputs, timeout_ms=self._budget(deadline), operation=operation
                )
                self.store.event(
                    event="condition_checked",
                    step_id=step_id,
                    action="verify",
                    policy_decision="allowed",
                    checkpoint="passed" if result else "failed",
                    control_state=self.control.state,
                )
                return result
            except PersistenceError:
                await self._session.close()
                raise

    async def preview(self, step):
        """Guarded model observation: presence and state only, no UI text or values."""
        step = Step.model_validate(step)
        async with self._lock:
            deadline = monotonic() + self._config.runtime.step_timeout_seconds
            return await self._session.surface.preview(
                step.action,
                self._inputs,
                operation=step.operation,
                timeout_ms=self._budget(deadline),
            )

    async def report_failure(self, step, code, expected, observed):
        async with self._lock:
            return await self._failure(
                step, SurfaceError(code, expected, observed), 0, "not_checked"
            )

    def exclude_operator_wait(self, seconds):
        """Exclude bounded operator wait from the active execution deadline."""
        if (
            self.control.state not in {"RESUME_CHECK", "AUTOMATION_RUNNING", "FAILED"}
            or not 0 <= seconds <= 3600
        ):
            raise ValueError("Invalid operator wait adjustment")
        self._started_at += seconds

    def save_resolution(self, record):
        """The coordinator extends an already-sanitized intervention; preserve its schema."""
        from uuid import UUID

        from computer_use.schemas.intervention import Resolution

        record = Intervention.model_validate(record)
        if (
            record.run_id != self.run_id
            or record.session_id != self.session_id
            or record.resolution is None
        ):
            raise ValueError("Invalid resolved intervention")
        if str(UUID(record.id)) != record.id:
            raise ValueError("Invalid intervention identity")
        original = Intervention.model_validate_json(
            (self.store.directory / (record.id + ".json")).read_text()
        )
        if record.model_dump(exclude={"control", "resolution"}) != original.model_dump(
            exclude={"control", "resolution"}
        ):
            raise ValueError("Resolution must extend the original sanitized intervention")
        resolution = record.resolution
        if str(UUID(resolution.human_actions_ref)) != resolution.human_actions_ref:
            raise ValueError("Invalid human actions reference")
        safe = record.model_copy(
            update={
                "resolution": Resolution(
                    action=resolution.action,
                    operator_id=self._redactor.text(resolution.operator_id),
                    summary=self._redactor.text(resolution.summary),
                    human_actions_ref=resolution.human_actions_ref,
                    state_verified=resolution.state_verified,
                    verification=Diagnostic(
                        step_id=record.step_id,
                        expected=self._redactor.text(resolution.verification.expected),
                        observed=self._redactor.text(resolution.verification.observed),
                    )
                    if resolution.verification
                    else None,
                    resume_step_id=self._redactor.token(resolution.resume_step_id)
                    if resolution.resume_step_id
                    else None,
                )
            }
        )
        validated = Intervention.model_validate(safe)
        reference = str(uuid4())
        self.store._write(reference + ".json", validated.model_dump(mode="json"))
        return reference

    def save_intervention(self, record: Intervention):
        """Preserve trusted metadata and contract validity while redacting UI context."""
        from uuid import UUID

        record = Intervention.model_validate(record)
        if (
            record.run_id != self.run_id
            or record.session_id != self.session_id
            or record.resolution is not None
            or str(UUID(record.id)) != record.id
        ):
            raise ValueError("Intervention does not belong to this open run")
        step_id = self._redactor.token(record.step_id) if record.step_id else None
        context = self._safe_observation(record.context)
        safe = Intervention(
            schema_version="1.0",
            id=record.id,
            run_id=self.run_id,
            session_id=self.session_id,
            goal=self._redactor.text(record.goal),
            capability_id=self._redactor.text(record.capability_id)
            if record.capability_id
            else None,
            capability_version=record.capability_version,
            step_id=step_id,
            reason=record.reason,
            diagnostic=Diagnostic(
                step_id=step_id,
                expected=self._redactor.text(record.diagnostic.expected),
                observed=self._redactor.text(record.diagnostic.observed),
                evidence_ref=record.diagnostic.evidence_ref,
            ),
            context=context,
            control=record.control,
        )
        self.store._write(record.id + ".json", safe.model_dump(mode="json"))
        return safe

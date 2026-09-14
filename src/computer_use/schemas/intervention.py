"""Ownership and handoff records; sessions.control enforces live ownership locking."""

from typing import Literal, Self

from pydantic import model_validator

from computer_use.schemas.common import Contract, Identifier, Text, Version
from computer_use.schemas.observation import Observation
from computer_use.schemas.result import Diagnostic

ControlState = Literal[
    "AUTOMATION_RUNNING",
    "AWAITING_HUMAN",
    "HUMAN_CONTROL",
    "RESUME_CHECK",
    "COMPLETED",
    "FAILED",
]
Owner = Literal["automation", "human", "none"]
OWNERS: dict[str, str] = {
    "AUTOMATION_RUNNING": "automation",
    "AWAITING_HUMAN": "none",
    "HUMAN_CONTROL": "human",
    "RESUME_CHECK": "automation",
    "COMPLETED": "none",
    "FAILED": "none",
}
TRANSITIONS: dict[str, set[str]] = {
    "AUTOMATION_RUNNING": {"AWAITING_HUMAN", "COMPLETED", "FAILED"},
    "AWAITING_HUMAN": {"HUMAN_CONTROL", "FAILED"},
    "HUMAN_CONTROL": {"RESUME_CHECK", "FAILED"},
    "RESUME_CHECK": {"AUTOMATION_RUNNING", "AWAITING_HUMAN", "COMPLETED", "FAILED"},
    "COMPLETED": set(),
    "FAILED": set(),
}


class ControlSnapshot(Contract):
    session_id: Text
    state: ControlState
    owner: Owner

    @model_validator(mode="after")
    def matching_owner(self) -> Self:
        if self.owner != OWNERS[self.state]:
            raise ValueError("Control state and owner disagree")
        return self

    @property
    def automation_actions_allowed(self) -> bool:
        return self.state == "AUTOMATION_RUNNING" and self.owner == "automation"


class ControlTransition(Contract):
    before: ControlSnapshot
    after: ControlSnapshot
    reason: Text

    @model_validator(mode="after")
    def legal_transition(self) -> Self:
        if self.before.session_id != self.after.session_id:
            raise ValueError("Control transfer must preserve the session")
        if self.after.state not in TRANSITIONS[self.before.state]:
            raise ValueError("Illegal control transition")
        return self


class Resolution(Contract):
    action: Literal["resume", "complete", "abort"]
    operator_id: Text
    summary: Text
    human_actions_ref: Text
    state_verified: bool = False
    verification: Diagnostic | None = None
    resume_step_id: Identifier | None = None

    @model_validator(mode="after")
    def verified_return(self) -> Self:
        if self.action in ("resume", "complete") and (
            self.verification is None or not self.state_verified
        ):
            raise ValueError("Resume or completion requires recorded state verification")
        if (self.action == "resume") != (self.resume_step_id is not None):
            raise ValueError("Only resume requires a resume step ID")
        return self


class Intervention(Contract):
    schema_version: Literal["1.0"]
    id: Text
    run_id: Text
    session_id: Text
    goal: Text
    capability_id: Identifier | None = None
    capability_version: Version | None = None
    step_id: Identifier | None
    reason: Literal[
        "unknown_state",
        "recovery_exhausted",
        "policy_blocked",
        "no_progress",
        "step_limit",
        "timeout",
        "session_expired",
        "permission_denied",
    ]
    diagnostic: Diagnostic
    context: Observation
    control: ControlSnapshot
    resolution: Resolution | None = None

    @model_validator(mode="after")
    def consistent_context(self) -> Self:
        if (self.capability_id is None) != (self.capability_version is None):
            raise ValueError("Capability ID and version must be supplied together")
        if self.context.run_id != self.run_id or self.context.session_id != self.session_id:
            raise ValueError("Intervention context belongs to a different run or session")
        if self.control.session_id != self.session_id or self.diagnostic.step_id != self.step_id:
            raise ValueError("Intervention session or step context is inconsistent")
        expected = {"resume": "AUTOMATION_RUNNING", "complete": "COMPLETED", "abort": "FAILED"}
        if self.resolution is None:
            if self.control.state not in ("AWAITING_HUMAN", "HUMAN_CONTROL", "RESUME_CHECK"):
                raise ValueError(
                    "Open intervention must be paused, human-controlled, or checking resume"
                )
        elif self.control.state != expected[self.resolution.action]:
            raise ValueError("Resolution and final control state disagree")
        return self

"""Typed event envelope. Free-form content always crosses the redactor."""

from typing import Annotated, Literal

from pydantic import Field

from computer_use.schemas.common import Contract
from computer_use.schemas.intervention import ControlState


class Event(Contract):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    session_id: str
    mode: Literal["discovery", "replay"]
    sequence: Annotated[int, Field(ge=1)]
    event: Literal[
        "started",
        "completed",
        "failure",
        "control_change",
        "observation",
        "condition_checked",
        "recovery_started",
        "run_completed",
        "run_failed",
        "business_outcome",
        "model_requested",
        "model_response",
        "model_rejected",
        "artifact_created",
        "human_interaction",
        "handoff_requested",
        "resume_rejected",
        "handoff_resolved",
    ]
    step_id: str | None
    action: Literal["navigate", "fill", "click", "read", "wait", "verify"] | None
    policy_decision: Literal["allowed", "denied", "not_checked"]
    checkpoint: Literal["passed", "failed", "not_checked"]
    retry: Annotated[int, Field(ge=0, le=3)]
    control_state: ControlState
    evidence_ref: str | None = None
    details: dict = Field(default_factory=dict)

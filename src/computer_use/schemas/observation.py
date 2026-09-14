"""Surface-neutral observation metadata. Producers must sanitize text before persistence."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from computer_use.schemas.action import Target, input_references
from computer_use.schemas.capability import TargetIdentity
from computer_use.schemas.common import Contract, Identifier, Text


class ObservedControl(Contract):
    id: Identifier
    target: Target
    visible: bool
    enabled: bool
    text: Text | None = None


class Observation(Contract):
    schema_version: Literal["1.0"]
    run_id: Text
    session_id: Text
    sequence: Annotated[int, Field(ge=0)]
    target: TargetIdentity
    location: Text  # Sanitized path or desktop window identity; not session tokens.
    summary: Text
    controls: list[ObservedControl]
    state: Literal[
        "ready",
        "loading",
        "validation_error",
        "member_not_found",
        "permission_denied",
        "session_expired",
        "unexpected_dialog",
        "application_error",
        "unknown",
    ]
    evidence_ref: Text | None = None

    @model_validator(mode="after")
    def unique_controls(self) -> Self:
        if input_references(self.controls):
            raise ValueError("Observed controls must contain concrete text, not unbound inputs")
        ids = [control.id for control in self.controls]
        if len(ids) != len(set(ids)):
            raise ValueError("Observed control IDs must be unique")
        return self

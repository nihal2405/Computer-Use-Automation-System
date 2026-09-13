"""Terminal result contracts. Recoverable states are rules, not terminal success."""

from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, field_validator, model_validator

from computer_use.schemas.common import Contract, Identifier, Scalar, Text, Version


class RunContext(Contract):
    schema_version: Literal["1.0"]
    run_id: Text
    session_id: Text
    mode: Literal["discovery", "replay"]
    capability_id: Identifier | None = None
    capability_version: Version | None = None

    @model_validator(mode="after")
    def capability_context(self) -> Self:
        if (self.capability_id is None) != (self.capability_version is None):
            raise ValueError("Capability ID and version must be supplied together")
        if self.mode == "replay" and self.capability_id is None:
            raise ValueError("Replay results require a capability identity")
        return self


class Diagnostic(Contract):
    step_id: Identifier | None  # None means failure before the first step.
    expected: Text
    observed: Text
    evidence_ref: Text | None = None  # Opaque ID, not raw screenshot/DOM bytes.


class Success(RunContext):
    status: Literal["success"]
    checkpoint_verified: bool
    outputs: dict[Identifier, Scalar]

    @field_validator("checkpoint_verified")
    @classmethod
    def must_be_verified(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Success requires a verified checkpoint")
        return value


class BusinessOutcome(RunContext):
    status: Literal["business_outcome"]
    code: Identifier
    step_id: Identifier
    summary: Text


class Failure(RunContext):
    status: Literal["failure"]
    code: Literal[
        "invalid_input", "incompatible_target", "policy_denied", "target_not_found",
        "ambiguous_target", "checkpoint_failed", "timeout", "recovery_exhausted",
        "permission_denied", "session_expired", "application_error", "unknown_state",
        "step_limit", "no_progress", "invalid_model_response", "cancelled",
        "invalid_output", "persistence_failed", "model_request_failed",
    ]
    diagnostic: Diagnostic
    intervention_id: Text | None = None


ExecutionResult = Annotated[Success | BusinessOutcome | Failure, Field(discriminator="status")]
result_adapter = TypeAdapter(ExecutionResult)

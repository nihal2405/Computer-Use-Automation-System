"""Versioned workflow contracts and semantic validation across their components."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from computer_use.schemas.action import Action, Condition, Read, Timeout, input_references
from computer_use.schemas.common import Contract, Identifier, Scalar, Text, ValueSpec, Version, check_values
from computer_use.schemas.result import BusinessOutcome, ExecutionResult, Failure, Success, result_adapter


class TargetIdentity(Contract):
    product: Identifier
    version: Text
    surface: Literal["browser", "desktop"]


class TargetCompatibility(Contract):
    product: Identifier
    versions: Annotated[list[Text], Field(min_length=1)]
    surface: Literal["browser", "desktop"]

    @model_validator(mode="after")
    def unique_versions(self) -> Self:
        if len(self.versions) != len(set(self.versions)):
            raise ValueError("Target versions must be unique")
        return self


class Step(Contract):
    id: Identifier
    operation: Identifier  # Descriptive intent; never proof of policy permission.
    action: Action
    precondition: Condition | None = None
    postcondition: Condition | None = None
    timeout_ms: Timeout = 10_000


class BusinessOutcomeRule(Contract):
    code: Identifier
    when: Condition
    description: Text


class WaitRecovery(Contract):
    """Version 1 supports bounded waiting only, never retrying a side effect."""

    code: Literal["slow_loading"]
    strategy: Literal["wait_for"]
    when: Condition
    until: Condition
    max_attempts: Annotated[int, Field(ge=1, le=3)]
    timeout_ms: Timeout


class Capability(Contract):
    schema_version: Literal["1.0"]
    id: Identifier
    capability_version: Version
    description: Text
    provenance: Literal["development_fixture", "llm_discovery"]
    discovery_run_id: Text | None = None
    target: TargetCompatibility
    inputs: dict[Identifier, ValueSpec]
    outputs: Annotated[dict[Identifier, ValueSpec], Field(min_length=1)]
    steps: Annotated[list[Step], Field(min_length=1, max_length=100)]
    success_checkpoint: Condition
    business_outcomes: list[BusinessOutcomeRule] = Field(default_factory=list)
    recovery_rules: list[WaitRecovery] = Field(default_factory=list)

    @model_validator(mode="after")
    def connected_contract(self) -> Self:
        if (self.provenance == "llm_discovery") != (self.discovery_run_id is not None):
            raise ValueError("Discovery provenance requires a run ID; fixtures must not claim one")
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("Step IDs must be unique")
        for reference in input_references(self):
            name = reference.ref.removeprefix("inputs.")
            if name not in self.inputs:
                raise ValueError("An input reference is not declared")
            if self.inputs[name].type not in ("string", "decimal_string", "currency_code"):
                raise ValueError("UI text references must use a string-compatible input type")
        extracted = [step.action.output for step in self.steps if isinstance(step.action, Read)]
        if len(extracted) != len(set(extracted)):
            raise ValueError("Each output must be extracted exactly once")
        if set(extracted) != set(self.outputs):
            raise ValueError("Read actions must match all and only the declared outputs")
        for rules in (self.business_outcomes, self.recovery_rules):
            codes = [rule.code for rule in rules]
            if len(codes) != len(set(codes)):
                raise ValueError("Outcome and recovery codes must be unique within each category")
        if {rule.code for rule in self.business_outcomes} & {rule.code for rule in self.recovery_rules}:
            raise ValueError("A code cannot be both a business outcome and a recovery condition")
        return self

    def validate_inputs(self, values: dict[str, Scalar]) -> dict[str, Scalar]:
        check_values(self.inputs, values)
        return dict(values)

    def validate_outputs(self, values: dict[str, Scalar]) -> dict[str, Scalar]:
        check_values(self.outputs, values)
        return dict(values)

    def validate_target(self, identity: TargetIdentity) -> None:
        identity = TargetIdentity.model_validate(identity)
        if (
            identity.product != self.target.product
            or identity.surface != self.target.surface
            or identity.version not in self.target.versions
        ):
            raise ValueError("Target product, surface, or version is incompatible")

    def validate_result(self, result: ExecutionResult | dict) -> ExecutionResult:
        result = result_adapter.validate_python(result)
        if result.capability_id != self.id or result.capability_version != self.capability_version:
            raise ValueError("Result belongs to a different capability or version")
        if isinstance(result, Success):
            self.validate_outputs(result.outputs)
        if isinstance(result, BusinessOutcome):
            if result.code not in {rule.code for rule in self.business_outcomes}:
                raise ValueError("Business outcome is not declared by this capability")
            step_id = result.step_id
        elif isinstance(result, Failure):
            step_id = result.diagnostic.step_id
        else:
            step_id = None
        if step_id is not None and step_id not in {step.id for step in self.steps}:
            raise ValueError("Result refers to an unknown step")
        return result

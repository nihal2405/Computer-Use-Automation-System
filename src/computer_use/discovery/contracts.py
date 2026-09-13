"""A discovery goal defines the answer contract, never an ordered workflow."""

from typing import Literal, Self
from pydantic import Field, model_validator

from computer_use.schemas.action import Condition, Target, input_references
from computer_use.schemas.capability import BusinessOutcomeRule, Step, TargetCompatibility, WaitRecovery
from computer_use.schemas.common import Contract, Identifier, Text, ValueSpec, Version


class DiscoveryTask(Contract):
    schema_version: Literal["1.0"]
    id: Identifier
    capability_version: Version
    goal: Text
    target: TargetCompatibility
    inputs: dict[Identifier, ValueSpec]
    outputs: dict[Identifier, ValueSpec] = Field(min_length=1)
    output_targets: dict[Identifier, Target]
    success_checkpoint: Condition
    business_outcomes: list[BusinessOutcomeRule] = Field(default_factory=list)
    recovery_rules: list[WaitRecovery] = Field(default_factory=list)

    @model_validator(mode="after")
    def connected(self) -> Self:
        if set(self.output_targets) != set(self.outputs):
            raise ValueError("Output targets must match declared outputs")
        if any(ref.ref.removeprefix("inputs.") not in self.inputs for ref in input_references(self)):
            raise ValueError("Undeclared task input reference")
        for reference in input_references(self):
            if self.inputs[reference.ref.removeprefix("inputs.")].type not in {"string", "decimal_string", "currency_code"}:
                raise ValueError("UI references require string-compatible inputs")
        codes = [rule.code for rule in [*self.business_outcomes, *self.recovery_rules]]
        if len(codes) != len(set(codes)):
            raise ValueError("Outcome and recovery codes must be unique")
        return self


class Decision(Contract):
    command: Literal["act", "complete", "intervene"]
    step: Step | None
    explanation: Text

    @model_validator(mode="after")
    def matching_command(self) -> Self:
        if (self.command == "act") != (self.step is not None):
            raise ValueError("Only act decisions carry a step")
        return self


def response_schema():
    """Normalize Pydantic unions/defaults to the provider's strict JSON subset."""
    def convert(value):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {("anyOf" if key == "oneOf" else key): convert(item)
                  for key, item in value.items() if key not in {"default", "discriminator"}}
        if result.get("type") == "object":
            result["additionalProperties"] = False
            result["required"] = list(result.get("properties", {}))
        return result
    return convert(Decision.model_json_schema())

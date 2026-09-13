"""Record only successful execution; normalize bindings using reviewed policy templates."""

from computer_use.execution.targeting import bind_references
from computer_use.safety.policy import canonical, denied
from computer_use.schemas.capability import Step


class Recorder:
    def __init__(self, candidates, inputs):
        self.candidates = candidates
        self.inputs = dict(inputs)
        self.steps = []
        self.model_responses = []

    def normalize(self, requested):
        requested = Step.model_validate(requested)
        if requested.action.action in {"click", "fill", "navigate"} and any(s.action.action == "read" for s in self.steps):
            raise ValueError("Mutations after extraction would invalidate collected outputs")
        for candidate in self.candidates:
            if candidate.operation != requested.operation:
                continue
            if canonical(bind_references(candidate.action, self.inputs)) != canonical(bind_references(requested.action, self.inputs)):
                continue
            if candidate.action.action == "read" and candidate.action.output != requested.action.output:
                continue
            if requested.precondition is not None or requested.postcondition is not None:
                raise ValueError("Model conditions require independent review; use task checkpoint")
            if candidate.action.action == "read" and any(
                s.action.action == "read" and s.action.output == candidate.action.output for s in self.steps
            ):
                raise ValueError("An output was already extracted")
            # Copy the explicit input references from the matching permission.
            # Never replace strings elsewhere because they happen to equal an input.
            data = candidate.model_dump()
            data.update(id=f"step_{len(self.steps):03d}", timeout_ms=requested.timeout_ms)
            return Step.model_validate(data)
        raise denied()

    def append(self, step, outcome):
        if outcome.status != "success" or outcome.step_id != step.id:
            raise ValueError("Only successfully executed steps can be compiled")
        self.steps.append(Step.model_validate_json(step.model_dump_json()))

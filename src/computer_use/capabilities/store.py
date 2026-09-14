"""Sanitized capability export; compilation and replay remain separate components."""

import json
import os
from uuid import UUID, uuid4

from pydantic import ValidationError

from computer_use.observability.evidence import PersistenceError
from computer_use.safety.policy import canonical
from computer_use.schemas.capability import Capability


class ArtifactError(ValueError):
    def __init__(self):
        super().__init__("Artifact is missing, malformed, or unsupported")


class CapabilityStore:
    def __init__(self, directory, redactor):
        self.directory = directory
        self.redactor = redactor

    @staticmethod
    def load(path):
        try:

            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON key")
                    result[key] = value
                return result

            with open(path, "rb") as file:
                contents = file.read(1_048_577)
            if len(contents) > 1_048_576:
                raise ValueError("Artifact too large")
            return Capability.model_validate(json.loads(contents, object_pairs_hook=unique))
        except (OSError, ValueError, TypeError, RecursionError):
            raise ArtifactError() from None

    def save(self, capability):
        """Redact descriptions/identifiers; reject changes to execution semantics.

        Unlike diagnostic JSON, timeout integers must remain typed. They come only
        from the validated capability schema, never arbitrary input or model text.
        """
        try:
            original = Capability.model_validate(capability)

            def clean(value):
                if type(value) in {int, bool} or value is None:
                    return value
                if isinstance(value, str):
                    return self.redactor.text(value)
                if isinstance(value, list):
                    return [clean(item) for item in value]
                if isinstance(value, dict):
                    return {self.redactor.text(key): clean(item) for key, item in value.items()}
                raise ValueError("Unsupported capability value")

            cleaned = clean(original.model_dump(mode="json"))
            if original.discovery_run_id is not None:
                # A validated generated correlation ID, not arbitrary model prose.
                if str(UUID(original.discovery_run_id)) != original.discovery_run_id:
                    raise ValueError("Discovery run identity must be a generated UUID")
                cleaned["discovery_run_id"] = original.discovery_run_id
            sanitized = Capability.model_validate(cleaned)
            for before, after in zip(original.steps, sanitized.steps):
                if (
                    before.operation != after.operation
                    or canonical(before.action.model_dump()) != canonical(after.action.model_dump())
                    or canonical(before.precondition.model_dump() if before.precondition else None)
                    != canonical(after.precondition.model_dump() if after.precondition else None)
                    or canonical(
                        before.postcondition.model_dump() if before.postcondition else None
                    )
                    != canonical(after.postcondition.model_dump() if after.postcondition else None)
                ):
                    raise ValueError("Redaction would change an executable operation")
            if (
                original.target != sanitized.target
                or canonical(original.success_checkpoint.model_dump())
                != canonical(sanitized.success_checkpoint.model_dump())
                or set(original.inputs) != set(sanitized.inputs)
                or set(original.outputs) != set(sanitized.outputs)
            ):
                raise ValueError("Redaction would change invocation or checkpoint semantics")
            for before, after in zip(original.business_outcomes, sanitized.business_outcomes):
                if before.code != after.code or canonical(before.when.model_dump()) != canonical(
                    after.when.model_dump()
                ):
                    raise ValueError("Redaction would change a business outcome")
            for before, after in zip(original.recovery_rules, sanitized.recovery_rules):
                if canonical(before.model_dump()) != canonical(after.model_dump()):
                    raise ValueError("Redaction would change a recovery rule")
            self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
            path = self.directory / (str(uuid4()) + ".json")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as file:
                json.dump(sanitized.model_dump(mode="json"), file, indent=2)
                file.write("\n")
            return path
        except (OSError, ValueError, TypeError, ValidationError):
            raise PersistenceError() from None

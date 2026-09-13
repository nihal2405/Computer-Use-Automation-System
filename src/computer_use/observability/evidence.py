"""One redacting sink for events, failures, and future producer diagnostics."""

import json
import os
from pathlib import Path
from uuid import UUID, uuid4

from computer_use.observability.events import Event


class PersistenceError(RuntimeError):
    def __init__(self):
        super().__init__("Sanitized evidence could not be stored")


class EvidenceStore:
    def __init__(self, root: Path, redactor, *, run_id, session_id, mode):
        if str(UUID(run_id)) != run_id or str(UUID(session_id)) != session_id or mode not in {"discovery", "replay"}:
            raise ValueError("Invalid event identity")
        self.redactor = redactor
        self.run_id, self.session_id, self.mode = run_id, session_id, mode
        self._sequence = 0
        self.directory = root / run_id
        try:
            self.directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        except OSError:
            raise PersistenceError() from None

    def _write(self, filename, value, *, append=False):
        try:
            encoded = (json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n").encode()
            if len(encoded) > 1_048_576:
                raise ValueError("Evidence too large")
            flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | (os.O_APPEND if append else os.O_EXCL)
            descriptor = os.open(self.directory / filename, flags, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                file.write(encoded)
                file.flush()
        except (OSError, ValueError, TypeError):
            raise PersistenceError() from None

    def event(self, *, event, step_id=None, action=None, policy_decision="not_checked",
              checkpoint="not_checked", retry=0, control_state, evidence_ref=None, details=None):
        if evidence_ref is not None and str(UUID(evidence_ref)) != evidence_ref:
            raise ValueError("Invalid evidence reference")
        self._sequence += 1
        record = Event(
            run_id=self.run_id, session_id=self.session_id, mode=self.mode, sequence=self._sequence,
            event=event, step_id=self.redactor.token(step_id) if step_id else None,
            action=action, policy_decision=policy_decision, checkpoint=checkpoint, retry=retry,
            control_state=control_state, evidence_ref=evidence_ref,
            details=self.redactor.sanitize(details or {}),
        )
        self._write("events.jsonl", record.model_dump(), append=True)

    def diagnostic(self, kind, payload):
        if kind not in {"dom_structure", "artifact_diagnostic", "human_event", "model_explanation", "error", "result_diagnostic"}:
            raise ValueError("Unsupported diagnostic kind")
        reference = str(uuid4())
        self._write(reference + ".json", {"kind": kind, "details": self.redactor.sanitize(payload)})
        return reference

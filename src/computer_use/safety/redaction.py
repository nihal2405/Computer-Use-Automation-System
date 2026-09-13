"""Fail-closed text redaction: only reviewed constants survive verbatim."""

import hashlib
import hmac
import secrets

from pydantic import BaseModel

SAFE_WORDS = set("""
schema_version capability_version id description provenance discovery_run_id target inputs outputs
steps success_checkpoint business_outcomes recovery_rules product versions surface operation action balance currency
path strategy role name label text selector scope rationale value source ref literal input
condition expected kind timeout_ms output precondition postcondition type run_id session_id
sequence location summary controls state evidence_ref visible enabled code observed diagnostic
goal reason resolution operator_id step_id capability_id before after owner mode status
event policy_decision checkpoint retry attempt control_state details action_record observation
error model_explanation human_event artifact_diagnostic dom_structure nodes tag children disabled
truncated unavailable ready loading validation_error member_not_found permission_denied
session_expired unexpected_dialog application_error unknown allowed denied not_checked passed failed
started completed failure success control_change navigate fill click read wait verify
AUTOMATION_RUNNING AWAITING_HUMAN HUMAN_CONTROL RESUME_CHECK COMPLETED FAILED automation human none
discovery replay invalid_input policy_denied ownership_denied incompatible_target target_not_found
ambiguous_target target_not_visible unsupported_target browser_error checkpoint_failed timeout
session_closed session_not_started cancelled step_limit run_timeout retry_denied persistence_failed
string integer boolean decimal_string currency_code development_fixture llm_discovery browser
text_equals hidden css region dialog alert status textbox button link heading cell row table
tab tabpanel combobox label text wait_for slow_loading max_attempts until when version
html body main header footer nav aside section article div p span h1 h2 h3 h4 form label input
button a table caption thead tbody tr th td ul ol li dialog select option textarea fieldset legend
strong em details summary unknown_tag 1.0 1.0.0 / invalid_output persistence_failed
recovery_exhausted no_progress step_limit checkpoint_verified intervention_id policy_blocked
business_outcome condition_checked recovery_started run_completed run_failed result_diagnostic
model_requested model_response model_rejected artifact_created model_request_failed response_id
model provider openai command act complete intervene explanation filled condition_met
collected_outputs permitted_actions feedback requested_step response_received artifact_sha256
human_interaction handoff_requested resume_rejected handoff_resolved interaction tag role input_type
input change click submit focus navigation select textarea password checkbox radio search text
human_actions_ref action resume complete abort operator_id state_verified verification resume_step_id
""".split())
SAFE_WORDS.update({
    "An explicitly approved operation and destination", "Policy blocked this operation",
    "Exactly one target", "Multiple targets matched", "Target is absent",
    "Exactly one scope", "Multiple scopes matched", "Scope is absent",
    "Checkpoint condition satisfied", "Condition is false", "Deadline elapsed",
    "Operation within its deadline", "Automation ownership for this operation",
    "Configured product and version markers", "Missing or incompatible UI identity",
    "A validated step", "Invalid step contract", "An open browser session", "Session is closed",
    "Steps within the configured limit", "Step limit reached", "An uninterrupted operation",
    "Caller cancelled execution", "Execution within configured limits",
})


class Redactor:
    def __init__(self, trusted_text=()):
        self._trusted = frozenset(SAFE_WORDS | set(trusted_text))
        self._salt = secrets.token_bytes(32)
        self._secrets = set()

    def register(self, values):
        for value in values:
            if value is not None and str(value):
                self._secrets.add(str(value))

    def token(self, value: str) -> str:
        digest = hmac.new(self._salt, value.encode(), hashlib.sha256).digest()[:8]
        # Encode nibbles as a-p so a short numeric secret cannot reappear by
        # chance inside its opaque token (for example, "1001" in a hex digest).
        alphabet = "abcdefghijklmnop"
        encoded = "".join(alphabet[byte >> 4] + alphabet[byte & 0x0F] for byte in digest)
        return "redacted_" + encoded

    def text(self, value: str) -> str:
        if value in self._trusted and not any(secret in value for secret in self._secrets):
            return value
        return self.token(value)

    def sanitize(self, value, *, _depth=0):
        if _depth > 20:
            return "redacted_depth_limit"
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        if value is None or type(value) is bool:
            return value
        if isinstance(value, str):
            return self.text(value)
        if type(value) in {int, float}:
            # Numbers in arbitrary content may be balances, account numbers, or PINs.
            return self.token(str(value))
        if isinstance(value, dict):
            return {self.text(str(key)): self.sanitize(item, _depth=_depth + 1)
                    for key, item in list(value.items())[:1000]}
        if isinstance(value, (list, tuple)):
            return [self.sanitize(item, _depth=_depth + 1) for item in value[:1000]]
        raise ValueError("Unsupported persistence value")

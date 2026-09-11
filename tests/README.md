# Test plan

Tests are not implemented yet. Add meaningful checks as the behavior is built.

## Unit

- Schema rejection of unsupported versions/actions, missing parameters, invalid
  output contracts, and invalid checkpoint/parameter references.
- Policy rejection of unapproved origins, routes, operations, and risky actions;
  ambiguous target rejection and navigation/redirect boundary checks.
- Redaction of secrets and sensitive data before all persistence paths, including
  logs, artifacts, failure snapshots, and human-action capture.
- Exclusive ownership: no automation dispatch during human control; legal
  pause/takeover/resume transitions; bounded retry and stopping rules.

## Integration

- Replay a generated capability for another member with model calls disabled.
- Verify extracted outputs against visible UI and enforce the final checkpoint.
- Distinguish missing members from permission denial and other hard failures.
- Bound slow-load recovery and avoid replaying unsafe side effects.
- Preserve browser/session identity during handoff, record actual human events,
  and re-check state before resuming, including when a human completed the step.
- Verify sanitized failure evidence and clear expected/observed diagnostics.

Use mock model responses for unit tests only. A genuine live-model discovery run
is a separate required demonstration and cannot be replaced by a test double.

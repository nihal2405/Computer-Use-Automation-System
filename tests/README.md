# Verification

The complete suite passes **345 tests**. A separate successful manual handoff run
is preserved in [Phase 8 evidence](../evidence/phase8/README.md).

Current clean-environment acceptance passes **349 tests** and **40 additional
replay/handoff checks using the genuine artifact**. Four acceptance-runner tests
check credential exclusion, symlink rejection and honest test outcome reporting.
Eight separate real CLI scenarios are preserved alongside the test report.
See [acceptance](../docs/acceptance.md).

Phase 8 adds **19 Chromium handoff checks** in `integration/test_handoff.py`.
They drive browser events with simulated operators and cover safe resume,
exclusive ownership, redacted typing, cancellation, deadlines, and failure paths.
They are distinct from a person performing the [manual demo](../docs/handoff.md).

Phase 7 adds **44 discovery/provider checks** (20 unit and 24 integration). At that
milestone the full suite passed **326 tests**. A separate run of all **21 replay integration
checks** also passes against the genuine Gemini-generated artifact. See
[discovery](../docs/discovery.md) and [run evidence](../evidence/phase7/README.md).

Phase 6 adds **52 replay checks**: 31 unit checks and 21 real-browser/integration
checks. At Phase 6 completion the suite passed **282 tests**. They cover fresh parameter binding,
both balances, business outcomes, recovery/exhaustion, checkpoints, typed outputs,
app/permission/session errors, limits, ownership, cancellation, persistence, and
model-disabled CLI execution. See [replay](../docs/replay.md).

Phase 5 adds 23 unit safety checks and 33 Chromium shared-executor checks. They
cover strict configuration, denied routes/controls/requests/redirects, redaction
across supported persistence paths, sanitized artifact export, ownership, limits,
and failure evidence. At Phase 5 completion the suite passed **230 tests**. See
[the executor guide](../docs/safety-executor.md) for commands and boundaries.

The synthetic banking app has 31 server tests in `mock_app/test_app.py` and 16
Chromium tests in `mock_app/test_browser.py`. They cover both member workflows,
all seven exceptional scenarios, session isolation, dialog resolution, and mobile
layout. These app tests do not implement or prove
model discovery, capability replay, or automation handoff.

`integration/test_browser_surface.py` adds 30 real Chromium adapter/session tests.
They exercise both members through contract actions, checkpoint evaluation,
observation, precise/scoped targeting, bounded waits, exclusive ownership,
same-page simulated takeover, concurrent transfer, cancellation, isolation, and
shutdown. At Phase 4 completion the suite had **174 passing tests**. Actual human-event capture
and handoff orchestration now have separate coordinator tests described above.

Environment checks are implemented in `environment/test_environment.py`. Run
`uv run --locked python -m pytest -q` after installing Chromium. They load YAML,
validate its types, serve a temporary Flask page, launch Chromium, and verify a
real UI click. They also check rejection of an invalid configuration value.

These environment checks validate installation only. Contract tests in
`unit/test_contracts.py` cover structural and semantic validation, strict input
and output types, capability compatibility, handoff context, legal ownership
records, and the validation CLI. They run without a browser or model using
`uv run --locked python -m pytest -q tests/unit`.

Environment and schema checks alone are not evidence of a banking workflow or
runtime safety. The integration coverage above implements browser/session checks;
implemented replay and handoff checks are listed below.

## Unit

- Implemented: schema rejection of unsupported versions/actions, missing parameters, invalid
  output contracts, and invalid checkpoint/parameter references.
- Implemented: policy rejection of unapproved origins, routes, operations, and risky actions;
  navigation/redirect boundary checks. Ambiguous target rejection is already
  covered by browser integration tests.
- Implemented: redaction before supported logs, artifacts, failure snapshots, and
  human-event metadata writes. Browser event capture is covered by integration tests.
- Implemented in browser integration tests: exclusive ownership, legal
  pause/takeover/resume transitions, and bounded condition waits. The executor now
  restricts retries to timed-out waits and enforces step/run limits. No-progress
  detection is implemented by discovery; replay has bounded wait recovery.

## Integration

- Implemented with both the development fixture and a genuine Gemini-generated
  artifact: replay for another member with model imports blocked and API keys removed.
- Implemented: verify extracted outputs against visible UI and enforce the final checkpoint.
- Implemented: distinguish missing members from permission denial and other hard failures.
- Implemented: bound slow-load recovery and avoid replaying unsafe side effects.
- Implemented coordinator: preserve browser/session identity during handoff, record browser-originated events,
  and re-check state before resuming, including when a human completed the step.
- Implemented: verify sanitized failure evidence and clear expected/observed diagnostics.

Use mock model responses for unit tests only. A genuine live-model discovery run
is a separate required demonstration and cannot be replaced by a test double.

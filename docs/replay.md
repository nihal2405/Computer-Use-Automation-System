# Deterministic replay

Replay loads a saved workflow, substitutes invocation inputs, and follows its
ordered steps through the policy-checked browser executor. It makes no model
calls. The example below uses the hand-authored `development_fixture` for debugging.
For a recorded model-generated workflow, use `evidence/latest-demo/capability.json`.

## Run the demonstration

From the repository root, start the synthetic bank in one terminal:

```bash
uv run --locked python -m mock_app
```

In a second terminal:

```bash
uv run --locked computer-use replay tests/fixtures/read_savings_balance.json \
  --inputs '{"member_id":"2002"}' --headless
```

The result has `status: success`, `checkpoint_verified: true`, and outputs
`{"balance":"8040.20","currency":"USD"}`. Change only the invocation ID to
`1001` to obtain `1250.75 USD`. The artifact stays unchanged. The wrapper reports
`provenance: development_fixture`, `model_used: false`, and
`session_retained: false`. Remove `--headless` to watch Chromium execute.

The authorized caller receives raw extracted outputs on stdout. Treat redirected
stdout as sensitive; the redacted diagnostic store does not sanitize files that
the caller independently creates from this result.

Exit codes are **0** for success, **2** for a declared business outcome, and **1**
for validation, setup, or execution failure. Searching `9999` returns
`member_not_found` without any balance. Invalid inputs fail before browser startup.

To reproduce exceptional states in each fresh replay browser, stop the mock
server and restart it with, for example:

```bash
uv run --locked python -m mock_app --scenario permission_denied
```

Other choices are `invalid_input`, `missing_member`, `slow_loading`,
`session_expired`, `application_error`, and `unexpected_dialog`. `/demo` controls
affect their own browser session; the server flag sets the initial scenario for
new sessions. Restart without the flag to restore normal behavior.

## What is checked

The loader rejects duplicate JSON keys, oversized files, invalid contracts, and
unsupported schema versions. Before browser startup, replay validates exact input
names/types, target compatibility, and every action and condition against trusted
policy. The first step must navigate to the configured entry path. UI data and
artifact prose cannot grant permission.

The executor binds references for each step, resolves unique controls, enforces
ownership and navigation boundaries, and checks pre/postconditions. Replay checks
visible application state between steps and verifies the final account-owner
checkpoint. It returns success only when every required output also validates.
Decimal balances stay strings to preserve precision; integer and boolean outputs
have strict text conversions. Currency symbols and malformed values are not guessed.

Missing members are declared business outcomes. Invalid forms, denied access,
expired sessions, and application errors return distinct failure codes. Unknown
states/dialogs, incompatible UI versions, bad outputs, or failed checkpoints stop
the run. Failures never include partial outputs.

## Recovery and intervention

Version 1 supports only approved condition-based waiting. The fixture recognizes
the Loading indicator and waits for it to disappear. Its attempts share a
run-wide budget, capped by both the artifact's `max_attempts` and runtime
`max_retries + 1`. Each wait also respects step and total-run deadlines. The
engine never repeats a click, form submission, fill, or navigation for recovery.
Exhaustion returns `recovery_exhausted`; a non-loading unknown state stops directly.
This fixed sequence has no model-driven loop or heuristic no-progress detector.

Failures requiring review produce a schema-valid, sanitized intervention with the
goal, run/session IDs, stopped step, reason, expected/observed details, UI context,
and unresolved control state. The generated ID identifies a JSON file inside the
run directory. The session moves to `AWAITING_HUMAN`, which blocks automation.
Invalid inputs do not request takeover. Evidence-write failure closes the browser
and returns `persistence_failed`; it cannot promise a persisted intervention.

The Python context retains the current browser until the caller exits it:

```python
from pathlib import Path
from computer_use.replay.engine import ReplayEngine

async def replay_once():
    root = Path.cwd()
    async with ReplayEngine.from_project(
        root,
        artifact=root / "tests/fixtures/read_savings_balance.json",
        inputs={"member_id": "2002"},
    ) as engine:
        result = await engine.run()
        # A failed run's paused browser is still alive here.
        # engine.intervention contains the sanitized handoff request, if any.
        return result
```

By default the CLI is a batch command and closes its browser after every outcome.
Add `--interactive` to route a blocked run to the local operator UI while retaining
the same browser. Its coordinator captures value-free human events and verifies
the requested account before resuming fresh output reads. See [handoff](handoff.md).
Each engine starts once; verified resume continues that same run. Saved records
cannot resurrect a browser after the process exits.

## Evidence and tests

Structured replay events include action/checkpoint results, recovery attempts,
control changes, and terminal outcomes. Output/input values and unreviewed prose
are redacted before diagnostic persistence. Failures capture structural DOM
evidence rather than raw screenshots. Runs are stored under the configured,
Git-ignored run directory.

```bash
uv run --locked python -m pytest -q \
  tests/unit/test_replay_contracts.py tests/integration/test_replay.py
```

Tests exercise both members, not-found outcomes, delayed loading, exhaustion,
ownership during intervention, wrong-account checkpoints, invalid outputs,
app/permission/session errors, unknown states, incompatible versions, limits,
cancellation, persistence failures, and sanitized artifact reuse. A separate
process removes API keys and blocks model/discovery imports before loading the
CLI, then retrieves the second balance through Chromium. Browser request policy
also blocks external model endpoints. These are deterministic development checks;
recorded discovery and second-member reuse are documented in the
[latest demo](../evidence/latest-demo/README.md).

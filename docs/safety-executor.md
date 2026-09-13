# Shared execution, safety, and diagnostics

Phase 5 adds one executor, now used by replay and ready for future discovery. Both
modes use the same policy, browser adapter, ownership lock, deadlines, and redacting
persistence layer. Mode is recorded in events and does not change permissions.

## Configuration

Run this from the repository root to validate configuration without launching a browser:

```bash
uv run --locked computer-use validate-config
```

The loader reads `config/settings.yaml`, `config/targets/mock_bank.yaml`, and
`config/policy.yaml`. It rejects unknown fields, wrong types, duplicate YAML keys,
unapproved entry origins/routes, invalid patterns, path traversal in output
directories, and unsupported locator overrides. Model output cannot supply a new
policy through the action API. Loaded configuration is copied before use so later
mutation of the caller's models cannot widen a running executor's permissions.

Runtime settings control browser visibility, step/run deadlines, maximum dispatched
steps, retry limits, and output directories. `max_no_progress_steps` is validated
and reserved for the future run controller; this step executor does not decide
whether a goal is making progress. `.env` loading and model credentials are still
outside this phase. Configuration files are trusted operator input and must be
reviewed before changes; regexes and approved labels are not generated from UI text.

## Call the shared executor

Start the banking server with `uv run --locked python -m mock_app`. A minimal Python
caller can then execute a step using the installed project package:

```python
import asyncio
from pathlib import Path

from computer_use.execution.executor import Executor


async def main():
    async with Executor.from_project(
        Path.cwd(), mode="replay", inputs={"member_id": "2002"}
    ) as executor:
        outcome = await executor.execute_step({
            "id": "open_search",
            "operation": "search_member",
            "action": {"action": "navigate", "path": "/"},
        })
        assert outcome.status == "success"
        # Submit additional validated Step contracts through this same executor.


asyncio.run(main())
```

`execute_step` validates the step, applies configured limits, checks optional
preconditions, executes the action, and checks optional postconditions under the
same step deadline. A successful read returns its visible text to the authorized
caller in `StepOutcome.output`; the output is not persisted verbatim. A failed
checkpoint returns failure with no output. Failures include a code, step ID,
expected/observed diagnostics, and an opaque evidence reference.

The integration tests drive all seven hand-authored fixture steps and the final
member checkpoint for both members in both mode labels. They call this API directly;
they do not invoke a model. Separate [replay tests](replay.md) now exercise the
complete deterministic controller and its CLI.

## Permissions and browser boundaries

The policy has explicit operation/action rules. Each rule also identifies an
approved target, condition, or navigation path. Exact matching excludes explanatory
rationales, read-output slot names, and timeout values, which cannot grant permission.
Inputs must match configured names and patterns; this demo accepts only a 4–10 digit
`member_id`. A model cannot authorize an arbitrary button by calling it `search_member`.

The actual resolved control is checked too: fills permit text/search inputs,
links must lead to approved destinations, and submit buttons must have an approved
form action and method. Downloads, new-window targets, and visibly risky controls
are blocked. No transaction or deletion route is approved. Browser request checks
remain active if an event handler changes a link's behavior after its DOM check.

The browser context allows approved main-frame navigation and separately approved
static assets. It blocks API fetches, background submissions, other frames, popups,
WebSockets, and service workers. A POST requires a one-use permit for the currently
approved form destination. There is no automatic retry of a submission. Queries,
credentials, encoded paths, and unsupported URL schemes fail the canonical URL checks.

Normal Playwright routing alone did not intercept every redirect in the tests.
The Chromium adapter therefore also pauses responses with the
[Chrome DevTools Fetch protocol](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/).
It validates each redirect destination before releasing the response, rejects
redirects that would repeat a POST, and blocks attachment responses. Tests check
server-side request counts, so a blocked destination must never receive a request.
This implementation is Chromium-specific; other browser backends are unsupported.

A blocked browser request latches the boundary closed for subsequent operations.
Create a new executor after correcting the trusted configuration or application;
UI text cannot reset the latch. Pre- and post-action checks also verify the current
origin/route and the configured product/version markers.

These controls assume the approved application's endpoint semantics are trusted.
An allowlist cannot establish that an approved POST remains read-only if its server
implementation changes. This is an application boundary, not an OS sandbox against
arbitrary Python code or a compromised browser. Future controllers must use the
executor; the low-level unguarded `BrowserSession` remains available for adapter tests.

## Ownership, deadlines, and retry behavior

The executor serializes steps and its public `transition` method. The browser's
ownership lock checks access again at dispatch. Human control blocks automation;
resume checks permit inspection and verification but reject mutations. Transitions
are recorded through a hook under the ownership lock. If the event cannot be saved,
the transition is not accepted and the executor closes the browser.

Waits observe conditions within a bounded deadline. Explicit retries are allowed
only for the immediately preceding identical timed-out wait, with consecutive retry
numbers capped by configuration. Clicks, fills, and navigation cannot be retried
through the retry parameter. There is no automatic recovery loop. Step and run limits
are enforced before dispatch; cancellation records a failure, and interrupted
mutations retain the adapter's fail-closed context cleanup.

The browser boundary remains active during manual ownership. Operator-only demo
and session-restart routes are not granted to automation. A full operator interface,
operator-specific permissions, actual human-event capture, and intervention routing
remain later work; tests simulate control changes and human-event metadata.

## Redaction and files

Every supported persistence method uses a shared redactor. It retains only reviewed
UI constants and fixed schema/diagnostic vocabulary. Other strings, unknown keys,
and arbitrary numeric values become HMAC tokens using a random per-run key that is
not saved. Known input/output values are registered and take precedence over the
allowlist. Unknown names, API keys, and free-form model explanations are therefore
removed without needing to recognize every possible secret format.

This conservative approach sacrifices free-form readability. It is not a general
PII detector or a promise that arbitrary preexisting files are sanitized. Reviewed
policy constants must themselves be non-sensitive. Returned observations are
redacted projections; a future model/controller must handle opaque references and
parameter binding rather than using redacted strings as literal UI targets.

Each run writes under `runs/<generated-run-id>/`:

- `events.jsonl`: typed events with generated run/session IDs, mode, sequence,
  pseudonymous step ID, action, policy decision, checkpoint result, retry count,
  control state, and sanitized details.
- `<evidence-id>.json`: structural DOM failure evidence containing element types,
  nesting, visibility, and disabled state. No text, field values, URLs, scripts,
  cookies, or screenshots are collected. If ownership or lifecycle prevents
  inspection, the evidence explicitly records unavailability.
- Diagnostic exports for errors, model explanations, artifact diagnostics, and
  human-event metadata also cross the same redactor. A diagnostic artifact export
  is not an executable capability.

`executor.artifacts.save(capability)` provides a separate validated capability
export under the configured artifact directory. It redacts prose and untrusted
identifiers, preserves typed fields and input/output slot names, revalidates the
schema, and rejects any change to operational targets, parameter references,
checkpoints, business outcomes, or recovery conditions. Parameterize private literal
values or review genuinely public constants instead of saving a broken workflow.
Export does not compile a capability or prove its provenance.

Files use generated names and owner-only file permissions. A persistence failure
stops the executor and closes the browser; it must not report a successful step
whose audit event could not be stored. No raw traces, screenshots, or model logs
are written. These development outputs remain Git-ignored and are not submission
evidence of genuine model discovery or human intervention.

## Verification

```bash
uv run --locked python -m pytest -q tests/unit/test_safety.py tests/integration/test_safe_executor.py
uv run --locked python -m pytest -q
```

The safety tests cover configuration rejection, URL canonicalization, both modes
and both members, denied operations/routes, redirected requests, spoofed controls,
background requests, ambiguous targeting, ownership, deadlines, retry restrictions,
pre/postconditions, cancellation, persistence failure, and all supported redaction
paths. The full suite also retains the earlier contract, mock-app, environment,
and browser/session checks.

Verified: **230 tests passed**, including **23 safety unit tests** and **33 browser
safety tests**. `computer-use validate-config` now validates 13 reviewed rules,
including the loading-state probe used by [replay](replay.md).

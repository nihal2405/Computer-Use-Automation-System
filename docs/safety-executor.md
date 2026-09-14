# Shared execution and safety

Both discovery and replay call the same executor. It validates a step, binds
inputs, checks ownership and policy, resolves the target, performs the action,
checks conditions, and records the result. The execution mode changes event
metadata, not permissions.

## Configuration

```bash
uv run --locked computer-use validate-config
```

The loader reads runtime, target, and policy YAML. It rejects duplicate keys,
unknown fields, wrong types, invalid patterns, unapproved entry URLs, and output
paths that escape the project. Locator overrides are currently rejected.

Configuration is copied at executor construction. Changes to the caller's models
cannot widen an active run's permissions. Configuration itself is trusted input;
the model and target page cannot edit it through the action interface.

Runtime settings set step/run deadlines, step limits, retry bounds, browser
visibility, and output locations. Discovery also uses the no-progress limit.
Model credentials are loaded separately by the provider client.

## Policy and network checks

Every allowed action has an operation, target or condition, and destination where
applicable. The executor checks the resolved control too: input type, link target,
form action/method, and download or new-window behavior. A model cannot make an
arbitrary button safe by labelling it `search_member`.

The browser permits approved main-frame routes and local static assets. It blocks
background APIs, frames, popups, WebSockets, service workers, and downloads.
Submissions require a one-use permit for the approved form destination.
There is no banking transaction route in the policy.

Chromium's [CDP Fetch interception](https://chromedevtools.github.io/devtools-protocol/tot/Fetch/)
checks redirect destinations before releasing responses. Tests check that blocked
destinations receive no request. A denied request latches the boundary closed;
a page cannot clear it. This is why only Chromium is supported.

During human control, a separate rule permits the current member's dialog
acknowledgement POST with its CSRF field. It does not permit other account changes.

## Ownership and deadlines

Steps and ownership changes are serialized. Access is checked again after
acquiring the browser lock, so an action waiting in a queue cannot use an outdated
ownership decision. Resume checks allow reads and verification, not mutations.

Waits poll an observable condition within a deadline. Explicit retries are limited
to the immediately preceding identical timed-out wait, with consecutive retry
numbers. The controllers manage the recovery loop; clicks, fills, and navigation
are not retried. If a mutating browser command is interrupted, its context closes
before ownership is released.

## Persistence

The redactor preserves reviewed schema words and UI constants. Other text and
numbers become keyed tokens using a random per-run key that is not stored.
Registered input/output values override the allowlist. This keeps unknown names,
field contents, model explanations, and errors out of logs without relying on a
list of sensitive word patterns.

Each run writes to the ignored `runs/<run-id>/` directory:

- `events.jsonl`: action, policy, checkpoint, retry, and control events.
- UUID-named JSON files: sanitized results, interventions, human-event summaries,
  and structural failure evidence.

DOM evidence preserves hierarchy, tags, visibility, and disabled state. It omits
text, values, URLs, scripts, and cookies. If inspection is unavailable, the record
says so. Runtime capture does not save screenshots or raw browser traces; the
published UI screenshots were collected manually and reviewed separately.

Capability export is different from diagnostic export: it must remain executable.
It redacts prose, preserves parameter references and typed fields, then checks
that operational targets and conditions have not changed.

Files use owner-only permissions. A persistence error closes the browser and
returns failure instead of claiming an audited success.

## Limits and tests

Policy assumes a cooperating application with trusted endpoint semantics. It is
not an OS sandbox, and a reviewed constant must itself be safe to publish.
The low-level `BrowserSession` can be used without policy for driver tests;
discovery and replay use the guarded executor.

```bash
uv run --locked python -m pytest -q tests/unit/test_safety.py tests/integration/test_safe_executor.py
```

Tests cover denied routes, altered controls, redirects, background requests,
ambiguous targets, ownership, deadlines, cancellation, retry restrictions, and
redaction across persistence methods. [Recorded acceptance](../evidence/phase9-verified/README.md)
contains results for the archived source.

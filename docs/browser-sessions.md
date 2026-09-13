# Browser interaction and session management

Phase 5 now wraps this adapter in the [shared safe executor](safety-executor.md).
Use that entry point for application work. The API below describes the lower-level
adapter, which is also retained for isolated development tests.

Phase 4 implements the `Surface` protocol, a Playwright Chromium adapter, and a
session owner. Discovery and the future executor can use plain contracts without
receiving Playwright pages, locators, contexts, or browser objects.

## Use the adapter

Start the bank with `uv run --locked python -m mock_app`. The following Python
example uses the installed project package and a visible browser:

```python
import asyncio

from computer_use.schemas.capability import TargetIdentity
from computer_use.sessions.manager import BrowserSession


async def main():
    async with BrowserSession(
        base_url="http://127.0.0.1:8000",
        target=TargetIdentity(product="synthetic_bank", version="1.0", surface="browser"),
        run_id="local_example",
    ) as session:
        await session.surface.execute({"action": "navigate", "path": "/"})
        await session.surface.execute({
            "action": "fill",
            "target": {
                "strategy": "label",
                "label": {"source": "literal", "value": "Member ID"},
                "rationale": "Exact accessible label",
            },
            "value": {"source": "input", "ref": "inputs.member_id"},
        }, {"member_id": "2002"})
        observation = await session.surface.observe()
        assert observation.session_id == session.session_id
        # Continue with click/read/wait/verify contracts inside this same context.


asyncio.run(main())
```

The context closes the browser on exit, including when the caller raises an
exception. For a longer-lived operator application, call `start()` once, retain
the session across steps, and call `close()` explicitly at shutdown. Both methods
are idempotent; a closed session cannot restart. The default is headed mode for
manual use; integration tests use `headless=True`. No browser profile is persisted.
Use one asyncio event loop per session; cross-thread and cross-process access are
not supported.

## Operations and targeting

`surface.execute(action, inputs, timeout_ms=...)` validates and binds the existing
action contract before browser dispatch. Navigation, fill, click, wait, and verify
return `None`; read returns stripped visible element text. No output conversion,
capability orchestration, recovery policy, or terminal run result is implemented
here. `surface.evaluate(condition, inputs)` returns a boolean for current state;
`verify` raises `checkpoint_failed` when that condition is false.

Accessible role/name and label targets use exact matching. Text is exact under
Playwright's whitespace normalization. Optional CSS scopes must match exactly one
container. Targets must also match exactly one element. Missing actions fail with
`target_not_found`; duplicate scopes or targets fail with `ambiguous_target`.
The adapter never chooses `.first()` or filters duplicates down to a convenient
visible match. Role selectors follow accessibility-tree visibility rules; CSS and
label matches may include hidden elements. Reads require a visible element; fills
and clicks use Playwright's bounded actionability checks.

CSS is an explicit fallback for legacy markup. Selector engine chains, XPath,
coordinates, iframe traversal, and automatic popup switching are unsupported.
There is no visual targeting fallback for inaccessible canvas or desktop controls.
Playwright's strict locators recheck target uniqueness during action dispatch;
selectors are resolved afresh for every operation, not cached as element handles.

## Deadlines and conditions

The default operation budget is 5 seconds; callers may choose 1–60,000 ms. One
deadline covers ownership-lock acquisition, resolution, and the operation. A wait
uses its declared timeout, capped by an explicit caller timeout if supplied.

Wait checks the observable condition repeatedly, up to every 25 ms, until it is
true or the deadline expires. It never assumes a page is ready after a fixed sleep.
Missing or invisible targets are false for visible/text-equals and true for hidden.
Ambiguity is an immediate error even for hidden conditions. Text equality strips
leading/trailing rendered whitespace but does not normalize interior text. For a
slow-loading page, wait for the destination control before clicking it.

`SurfaceError` carries `code`, `expected`, and `observed`. Raw Playwright messages
are suppressed because they can contain values, URLs, or DOM snippets. Timeouts
never trigger an automatic retry of a side effect. If cancellation or the outer
deadline interrupts a mutating browser command, the session closes its context
before releasing ownership: cancelling a Python await alone cannot guarantee the
browser stopped acting. A timed-out or cancelled inspection wait does not close
the browser. The future executor must map adapter errors to run/step diagnostics.

## Ownership and takeover

All adapter operations and ownership changes share one lock. A transfer waits for
an active bounded operation to leave that lock. Ownership is checked after lock
acquisition, so a queued operation cannot use an earlier ownership decision.

Use `await session.control.transition(state, reason)` for legal transitions:

1. `AUTOMATION_RUNNING`: all adapter operations are allowed.
2. `AWAITING_HUMAN`: adapter access is blocked while awaiting an operator.
3. `HUMAN_CONTROL`: adapter access is blocked; the person uses the existing window.
4. `RESUME_CHECK`: observation, reads, condition checks, waits, and verification are
   allowed. Navigation, fill, and click remain blocked.
5. Return to `AUTOMATION_RUNNING` only after the caller verifies the appropriate
   checkpoint, or transition back to `AWAITING_HUMAN` when more help is needed.

`COMPLETED` and `FAILED` block operations and cannot transition back to running.
Transitions preserve the session ID, browser context, page, and cookies. The
handoff coordinator is responsible for requiring and recording a successful resume
checkpoint; this low-level transition method validates state order, not the reason's
truth. The [handoff coordinator](handoff.md) now supplies operator controls,
intervention routing, value-free browser event capture, and verified resume.
The lock governs this adapter's dispatch; it
cannot prevent a person from touching an unlocked browser while automation owns it.

## Observations and current boundaries

Observations contain run/session IDs, a monotonically increasing sequence, the
current path without query or fragment, a bounded accessibility snapshot summary,
and up to 100 visible, uniquely addressable controls. Accessible names come from
Playwright rather than a custom ARIA approximation. Controls use concrete role/name
targets and expose enabled state. Duplicate accessible targets are omitted from
the control list; manual targeting of them still fails explicitly.

This first integration checks the target's `data-product` and `data-version`
markers and maps recognized `body[data-state]` values into the shared observation
contract. Unknown states become `unknown`; missing or incompatible product markers
fail observation. These are cooperation markers for this synthetic target, not
an authentication mechanism or a generic vendor-detection system. Other targets
need an identity/state strategy. UI text can change between observation and action.

Raw adapter observations are in memory and can contain sensitive UI text. The shared
executor sanitizes observation projections and every supported persistence path.
It also loads policy, checks actions/controls, and installs request and redirect
guards. A manually created BrowserSession without a policy remains an unguarded
low-level development tool. No model calls or screenshots are recorded by this adapter.

## Verification

```bash
uv run --locked python -m pytest -q tests/integration/test_browser_surface.py
uv run --locked python -m pytest -q
```

The 30 Chromium integration checks exercise both member balances using the
hand-authored fixture's operations, exact/scoped targeting, visible-text extraction,
checkpoints, real slow loading, bounded waits, every operation denied during human
control, concurrent transfer and queued actions, cancellation, isolated sessions,
and shutdown. A simulated operator resolves the mock dialog on the same page and
returns through a checked resume state. This is adapter test coverage, not evidence
of model discovery, a replay engine, or an actual recorded human intervention.
The complete project suite passes 174 tests, including the 30 new adapter/session checks.

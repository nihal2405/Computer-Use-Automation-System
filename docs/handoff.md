# Human takeover and verified resume

Interactive discovery and replay keep the existing Chromium page alive when a run
needs help. A separate, local operator screen shows the trusted task goal, stopped
action, reason, run/session IDs, and sanitized intervention. It never shows input
values, balances, credentials, or raw page text.

## Try the complete workflow

From the repository root, run:

```bash
uv run --locked python scripts/handoff_demo.py
```

This starts a private synthetic bank on an available loopback port, enables its
unexpected-dialog scenario, and replays the preserved Gemini-generated capability
for member `2002`. It does not call a model or need an API key. Chromium is visible.
The terminal prints an `operator_url`; open that exact URL, including its fragment.

1. Wait for the operator screen to show `AWAITING_HUMAN`.
2. Select **Take control**, then **Show bank window** if needed.
3. In that same bank window, select **Continue to accounts**.
4. Return to the operator screen and select **Verify and resume**.
5. The terminal should report success with `8040.20 USD`. Both servers and the
   browser close when the command finishes. Diagnostics stay in the configured
   Git-ignored run directory.

To exercise an existing server instead:

```bash
uv run --locked python -m mock_app --scenario unexpected_dialog
# In another terminal:
uv run --locked computer-use replay evidence/phase7/capability.json \
  --inputs '{"member_id":"2002"}' --interactive --operator-timeout 900
```

`discover --interactive` uses the same operator interface and requires the selected
provider's key. Do not combine `--interactive` with `--headless`. Without the flag,
the CLI remains a batch command and closes the browser after its result.

## Control and verification

The sequence is `AUTOMATION_RUNNING → AWAITING_HUMAN → HUMAN_CONTROL → RESUME_CHECK`.
Automation dispatch is blocked throughout human ownership. The same page, context,
cookies, and session ID survive the handoff; the operator UI is a separate surface.
The operator cannot submit arbitrary automation commands through this UI.

Before resume, the coordinator freezes the cooperating page's event handlers,
drains pending capture events, and inspects it through the shared executor. It
requires the compatible banking target, ready state, the exact requested member's
accounts route, the account-owner checkpoint, and every declared output target.
Unexpected pages, wrong owners, unresolved dialogs, and missing outputs remain
paused. Take control again to correct them, or cancel. A latched network-policy
violation cannot be cleared by handoff; cancel and start a new run.

Successful verification grants a single-use resume permission. Replay continues
at the first output read only if the remaining suffix contains reads, waits, and
verification; it refuses to skip or repeat later mutations. All outputs are read
again, type-validated, and checked against the final checkpoint. If the human has
already completed the interrupted navigation, automation does not click it again.
This is a deliberately conservative savings-workflow resume strategy, not a
general workflow-repair planner.

Human-assisted discovery returns verified outputs with `human_assisted: true`.
It does **not** compile a capability from an incomplete model action history.
Unrecorded human actions cannot be presented as a fully model-discovered workflow.
Ordinary model-only discovery and artifact generation are unchanged.

Operator waiting has its own deadline: 900 seconds by default, configurable from
1 to 3600. Waiting does not consume the active execution budget. Step and recovery
bounds remain in effect, and at most three interventions are opened per run.
Cancel, operator timeout, browser closure, or an interrupted control command ends
the run safely. Commands are bounded to 30 seconds. Evidence-write failures close
the browser and report `persistence_failed`.

## Capture, permissions, and privacy

Browser event listeners capture trusted click, input, change, submit, and focus
events during human ownership, plus main-frame navigation events. They send only
the event category and a small allowlist of HTML tag types. They never read or
send field contents, passwords, keystrokes, text, selectors, IDs, URLs, cookies,
or arbitrary attributes. Events join the existing ordered run log. The resolution
links to the original intervention and a separate sanitized human-event summary;
the `handoff_resolved` event carries the resolution's opaque evidence reference.
The capture system saves no screenshots, video, browser traces, or raw model
transcripts. Manually collected screenshots are reviewed separately.

All browser request boundaries remain active during human control. A separate
reviewed policy rule permits only the dialog's form-encoded acknowledgement POST
for the current input member: fixed `decision=acknowledge` and a single CSRF field
which the app validates. It does not grant automation this POST permission or
allow transfers, other members' submissions, extra fields, or arbitrary APIs.

The operator server binds only to `127.0.0.1`, uses an unguessable bearer token,
checks Host and Origin, disables caching, and rejects unrecognized commands.
The initial token lives in the URL fragment and is removed from the address bar;
it is not sent in request paths or access logs. Keep the printed URL private.
Reloading the page requires reopening the original printed URL. This is a
single-user local tool, without remote authentication or multi-user roles.

Ownership strictly gates the automation executor. DOM event suppression and
capture assume the cooperating mock application; they cannot lock the operating
system, developer tools, address bar, or a malicious browser extension. The event
log is value-free interaction evidence, not a tamper-proof forensic recording.
Avoid touching the bank window while automation owns it.

## Verification and evidence

```bash
uv run --locked python -m pytest -q tests/integration/test_handoff.py
uv run --locked python -m pytest -q
```

The 19 Chromium integration cases cover same-session handoff, exclusive dispatch,
dialog resolution, a human completing an interrupted navigation, unexpected pages,
wrong owners, missing outputs, redacted typing, API authorization, narrow POST
permissions, duplicate resume, one-use verification, active/wait deadlines,
cancellation, closed windows, interrupted verification, persistence failure, and
human-assisted discovery returning verified outputs without compiling a capability.

These tests drive real browser events with **simulated operators**.
A separate manual operator demonstration also completed successfully; its 53
sanitized events, original intervention, resolution, failure evidence, and hash
manifest are preserved in [evidence/phase8](../evidence/phase8/README.md).
The [latest manual demo](../evidence/latest-demo/README.md) adds another recorded
handoff. Test counts in older manifests refer to their original source revisions.

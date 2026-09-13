# Synthetic banking application

Northstar is a local Flask application containing fictional members and accounts.
It provides the target UI for model discovery, deterministic replay, and
same-session human handoff.

## Run and try the workflow

After following [environment setup](../docs/environment.md), run from the repository root:

```bash
uv run --locked python -m mock_app
```

Open [the banking app](http://127.0.0.1:8000). Search for a member ID, click the
matching result, then open **Accounts** and read **Savings**:

- `1001`: Avery Morgan, savings `1250.75 USD`.
- `2002`: Jordan Ellis, savings `8040.20 USD`.

Use `--port 8001` to choose another port. Stop the server with Ctrl+C.
The server binds to the local loopback address and runs without debug mode.

## Controlled scenarios

Open **Demo controls**, select a scenario, and apply it before starting a search.
These controls affect that browser session. To initialize fresh automation
sessions in a scenario, start the server with `--scenario slow_loading` (or another
scenario ID). Restart without this flag for normal behavior. See
[replay.md](../docs/replay.md) for automated demonstration commands.

- **Normal:** both members complete the workflow. IDs must contain 4–10 ASCII
  digits. An invalid ID produces a validation error; an unknown ID such as
  `9999` produces “No matching member.”
- **Invalid input:** even a normally valid ID produces a validation error.
- **Missing member:** a valid search returns no matching member.
- **Slow loading:** results remain unavailable for approximately 1.8 seconds.
  The loading page refreshes automatically; it does not contain hidden results.
- **Permission denied:** opening Accounts returns a 403 page without balances.
- **Session expired:** opening Accounts returns a 401 page. Use the restart
  control, search again, and continue. This simulates expiry, not authentication.
- **Application error:** opening Accounts returns a controlled 503 page.
- **Unexpected dialog:** opening Accounts requires a person to select
  **Continue to accounts**. Escape cannot dismiss it. Acknowledgement persists
  for that member in the current demo session; blocked HTML contains no balances.

Applying a scenario clears previous search and recovery state. Select Normal to
return to the baseline workflow. Separate browser contexts have independent demo
state; tabs in the same context share cookies. Restarting the server resets signed
sessions. The dialog is a target-app obstacle used by the implemented takeover
and verified-resume demonstration. See [the handoff guide](../docs/handoff.md).

## Implementation boundaries

Synthetic records live only in `mock_app/data.py`. There is no balance data API.
Automation must navigate and read the visible UI, never import the data module.
Templates expose accessible labels and stable targets used by the development
fixture and genuine generated capability. Adapter and replay integration tests
exercise the complete workflow and checkpoint against both members.

POST forms use CSRF tokens, state is scoped to signed browser sessions, and local
static assets require no CDN. `/demo` and `/session/restart` are operator controls
and stay outside the automation allowlist. Runtime policy enforcement belongs to
the shared executor rather than the target application.

## Verification

```bash
uv run --locked python -m pytest -q tests/mock_app
uv run --locked python -m pytest -q
```

The app has 31 server checks and 16 Chromium checks covering both members, every
scenario, session isolation, blocked data, dialog resolution, and a mobile viewport.
At Phase 3 completion, the project suite passed all 144 tests. The completed
fresh-environment acceptance suite passes 349 tests, including browser, replay,
discovery, safety, and handoff coverage. Both normal member workflows were also
inspected interactively in the browser.

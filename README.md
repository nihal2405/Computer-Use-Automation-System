# Computer-Use Automation System

This project learns a browser workflow with an LLM, saves the successful steps,
and replays them with new inputs without calling the model again.

I used a small synthetic banking app to make the behavior easy to check. The task
is to find a member, open their accounts, and read their savings balance. When a
dialog blocks the workflow, a person can take over the same browser and return
control after the system checks the page.

The [latest demo](evidence/latest-demo/README.md) includes the generated capability,
discovery and replay logs, and screenshots from a manual handoff. The earlier
[fresh-environment acceptance run](evidence/phase9-verified/README.md) passed 349
tests, 40 additional checks against a generated artifact, and eight CLI scenarios.

## Setup

Use Python 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From the repository root:

```bash
uv sync --locked
uv run --locked python -m playwright install chromium
uv run --locked computer-use validate-config
uv run --locked python -m pytest -q
```

The lockfile records dependency versions. Development and browser tests were run
on macOS arm64; other platforms are unverified. Tests use local servers and need
no model key. See [environment setup](docs/environment.md) for details.

## Try the app

```bash
uv run --locked python -m mock_app
```

Leave this terminal running and open [the bank](http://127.0.0.1:8000). Search for
a member, open the result, and select **Accounts**:

- Member `1001`: savings `1250.75 USD`.
- Member `2002`: savings `8040.20 USD`.

All records are fictional. **Demo controls** lets you try loading delays, missing
members, permission errors, session expiry, application errors, and the handoff
dialog. To apply a scenario to a new automation browser, start the server with
`--scenario unexpected_dialog`, for example. [App guide](mock_app/README.md)

## Discover a workflow

Only discovery needs a live model connection and may incur API charges. Set
`GEMINI_API_KEY` in the ignored `.env` file. Copy `.env.example` only if you do
not already have a `.env`. The default is Gemini 3.6 Flash with low reasoning;
OpenAI is also supported through [provider configuration](docs/discovery.md).
An exported environment variable takes precedence over the file.

With the bank running, open another terminal:

```bash
uv run --locked computer-use discover \
  --goal "Read the requested member's savings balance and currency" \
  --inputs '{"member_id":"1001"}' --headless
```

A successful result includes an `artifact` path, verified outputs, and the number
of model responses. Copy that path into the replay command below. A model failure
produces no capability.

## Replay with another member

```bash
uv run --locked python scripts/replay_without_model.py \
  "PATH_RETURNED_BY_DISCOVERY" --inputs '{"member_id":"2002"}' --headless
```

To try replay without first running discovery, use the saved artifact:

```bash
uv run --locked python scripts/replay_without_model.py \
  evidence/latest-demo/capability.json --inputs '{"member_id":"2002"}' --headless
```

Expect `8040.20 USD`, `checkpoint_verified: true`, and `model_used: false`.
The wrapper removes API-key variables and blocks model, discovery, and mock-app
imports in the replay process. The separate Flask process owns the bank data;
automation reads it through Chromium.

Try `9999` to get `member_not_found` with no balance. Exit codes are 0 for
success, 2 for a business outcome, and 1 for a failure. Omit `--headless` to watch
the browser. [Replay details](docs/replay.md)

## Human takeover

```bash
uv run --locked python scripts/handoff_demo.py
```

This starts its own bank and a visible Chromium window; it needs no API key.
Open the operator URL printed in the terminal, select **Take control**, acknowledge
the bank's dialog, then select **Verify and resume**. The result appears in the
terminal, and the browser closes. Keep the operator URL private.

The script uses the older Phase 7 capability. To try a different artifact against
an existing server, use `computer-use replay PATH --inputs JSON --interactive`.
[Handoff details](docs/handoff.md)

## Tests and code checks

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m pytest -q
python3 scripts/acceptance.py --output runs/acceptance-review
```

The acceptance command creates a fresh source copy and locked virtual environment.
It needs a new output directory each time and does not call a model. It may reuse
download and browser caches. [Acceptance guide](docs/acceptance.md)

## Repository layout

- `src/computer_use/`: contracts, discovery, replay, browser sessions, policy,
  diagnostics, and the local operator interface.
- `mock_app/`: the synthetic bank, templates, and scenario controls.
- `config/`: runtime limits, model settings, target identity, and allowed actions.
- `tests/`: unit, environment, app, and browser integration tests.
- `scripts/`: model-free replay, manual handoff, and acceptance entry points.
- `evidence/`: inspected run records, generated capabilities, and demo images.
- `docs/`: component guides and setup notes.
- [REPORT.md](REPORT.md): design decisions and limitations; also available as a
  [three-page PDF](output/pdf/design-report.pdf).

## Scope

Discovery chooses steps within a reviewed vocabulary of banking controls. It does
not explore arbitrary websites or invent locators. Native desktop support and a
tenant registry are design extensions, not implemented features.

The operator interface is a local, single-user tool. Ownership checks block
automation during takeover, but they cannot lock the OS or browser developer
tools. The target is a cooperating demo app, not a production banking system.
Runtime outputs stay in ignored `runs/`; only inspected evidence is committed.

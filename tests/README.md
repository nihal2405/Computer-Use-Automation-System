# Tests

Run the offline suite from the repository root:

```bash
uv run --locked python -m pytest -q
```

Chromium must be installed. Tests start disposable servers on local ports and
need no model key. Model transports use test responses, not billable API calls.

## Test layout

- `unit/`: contracts, CLI validation, configuration, redaction, artifact loading,
  provider responses, compilation, and acceptance-report behavior.
- `environment/`: package setup, local server, and a basic Chromium interaction.
- `mock_app/`: app routes, synthetic members, exceptional states, and UI layout.
- `integration/`: targeting, request policy, browser ownership, replay, discovery
  control flow, and handoff. `conftest.py` supplies the bank fixture shared by
  replay, discovery, and handoff tests.

The [development artifact](fixtures/README.md) is hand-authored. To run replay and
handoff checks against a generated artifact instead:

```bash
REPLAY_TEST_ARTIFACT=evidence/latest-demo/capability.json \
  uv run --locked python -m pytest -q \
  tests/integration/test_replay.py tests/integration/test_handoff.py
```

The tests check more than a successful sequence of clicks: changed UI outputs,
wrong account owners, loading exhaustion, missing members, denied permission,
expired sessions, policy violations, cancellation, and failed evidence writes.

Handoff tests use simulated operators in real Chromium. Manual demonstrations are
recorded separately under [evidence](../evidence/README.md). Passing a test double
does not establish that a live provider works.

## Code checks

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
```

Ruff is pinned in the development dependencies. The replay wrapper intentionally
installs its import blocker before importing the CLI; that import has a narrow
lint exception.

## Acceptance

```bash
python3 scripts/acceptance.py --output runs/acceptance-review
```

This installs a new locked environment, runs the suite and generated-artifact
checks, and captures real CLI scenarios. Use a new output directory each time.
[Acceptance guide](../docs/acceptance.md) explains what is recorded and which
caches can be reused. Historical test counts belong to the revisions named in
those reports, not automatically to the current working tree.

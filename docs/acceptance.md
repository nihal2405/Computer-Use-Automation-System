# Integrated acceptance and reviewer commands

Run all commands from the repository root. The target contains synthetic data;
no real bank account or external banking service is involved.

## Install and start the mock app

```bash
uv sync --locked
uv run --locked python -m playwright install chromium
uv run --locked computer-use validate-config
uv run --locked python -m mock_app --port 8000 --scenario normal
```

Keep that terminal running. The bank is at `http://127.0.0.1:8000`. Use another
terminal for discovery or replay. The first install requires network access.

## Genuine discovery

Put `GEMINI_API_KEY` in the Git-ignored `.env`; the configured provider/model are
in `config/discovery.yaml`. OpenAI is also supported with `OPENAI_API_KEY` and the
corresponding provider configuration. Credentials must never enter tracked files.

```bash
uv run --locked computer-use discover \
  --inputs '{"member_id":"1001"}' --headless
```

This command calls the configured real model and may incur usage charges. It
prints a generated artifact path only after verified completion. API failures
are failures; a test fixture is never substituted for a failed discovery run.
See [discovery](discovery.md) for provider settings, limits, and provenance.

## Model-free replay and business outcomes

Use the newly printed artifact path to replay that discovery. The preserved
genuine Gemini artifact also provides a reproducible demonstration without a key:

```bash
uv run --locked python scripts/replay_without_model.py evidence/phase7/capability.json \
  --inputs '{"member_id":"2002"}' --headless
uv run --locked python scripts/replay_without_model.py evidence/phase7/capability.json \
  --inputs '{"member_id":"9999"}' --headless
```

The first returns `8040.20 USD` with a verified account-owner checkpoint and exit
code 0. The second returns `business_outcome / member_not_found`, no balance,
and exit code 2. Hard failures use exit code 1. The wrapper removes API-key
environment variables and rejects model/discovery and mock-app imports before
loading replay. Only the separate hosting process imports the mock application.

To demonstrate a hard failure, stop the mock server and restart it with
`--scenario permission_denied`, then repeat the second-member replay. Expect
`failure / permission_denied`, a sanitized intervention, and structural DOM
evidence. Do not call that a successful balance lookup. Use `--scenario normal`
again for ordinary replay.

## Same-session human takeover

The self-contained demo starts its own bank on an available port:

```bash
uv run --locked python scripts/handoff_demo.py
```

Open the printed operator URL, select **Take control**, and resolve the dialog
with **Continue to accounts** in the existing bank window. Then select **Verify
and resume**. The result appears in the terminal; browser and servers close.
No model is called. For an already running server, add `--interactive` to replay
or discovery. See [handoff](handoff.md) for cancellation, deadlines, capture, and
the conservative savings-page resume strategy.

## Fresh-environment acceptance

```bash
python3 scripts/acceptance.py --output runs/acceptance-review
```

Choose a new output directory each time; the runner refuses to overwrite evidence.
It copies an explicit set of current sources, including locally untracked project
files, into a temporary directory, excludes `.env`, environments, caches, and run
data, and installs a **new virtual environment from `uv.lock`**. It runs:

1. Configuration validation and the full offline test suite.
2. The replay and handoff integration suites with the genuine saved capability.
3. Eight real model-disabled CLI/browser runs: success, not-found, permission
   denial, session expiry, application error, invalid input, recovered loading,
   and recovery exhaustion.

Replay children cannot import the hosting application or model code. Success
outputs are compared in memory; persisted values remain redacted. Server request
counts check that recovery does not submit the search again. Expected failure
outcomes stay labelled failures; each scenario separately records whether it
matched the acceptance expectation. Failure cases require a structural snapshot.

The report records exact package versions, platform, SHA-256 hashes of source,
artifact and evidence, test counts, and stage exit codes. `source.tar.gz` contains
the exact credential-free source snapshot used for the run, before generated
files existed. JUnit outcomes are reduced to counts and source test identifiers;
tracebacks, parameter values, and captured output are not exported. Failed stages
produce a failed report and a nonzero exit code; nothing generates replacement
success evidence.

This is a fresh source copy and virtual environment on the same macOS host.
Package downloads and Playwright's matching browser cache may be reused. It is
not a clean OS, an independent hardware check, or a Git clone. The snapshot and
hashes identify exactly
what was tested. The runner leaves its temporary workspace available for local
diagnosis and does not alter the project's `.venv` or start billable model calls.

## Coverage and evidence map

- **Genuine model decisions and generated capability:** [latest demo](../evidence/latest-demo/README.md)
  and [Phase 7](../evidence/phase7/README.md),
  with matching discovery run IDs and artifact hash. That historical run is not
  relabelled as a new model call from the clean environment.
- **UI-only access and new-input reuse:** model-disabled CLI scenarios plus replay
  integration checks, including changed UI values and owner checkpoints.
- **Taxonomy and bounded recovery:** explicit not-found and failure examples,
  wait-only recovery, one search submission, and exhaustion diagnostics.
- **Safety and redaction:** `test_safety.py`, `test_safe_executor.py`, contract
  rejection tests, and checks before scenario evidence export. These exercise
  unapproved navigation, risky controls, ambiguous targets, redirects, and failed
  evidence writes.
- **Exclusive same-session takeover:** handoff tests against the genuine artifact
  plus the separate [manual operator run](../evidence/phase8/README.md). Automated
  handoff tests use simulated operators and do not impersonate manual evidence.
- **Rich failure evidence:** sanitized DOM structure retains tags, roles,
  visibility and hierarchy, without text, field values, URLs or screenshots.

Historical discovery evidence has an artifact hash and run correlation but did
not capture a full source snapshot at discovery time. The acceptance snapshot
cannot retroactively prove that historical source revision. Phase 8 includes
core-runtime hashes; the new acceptance report identifies the current sources.
These local records are reproducible evidence, not provider-signed attestations.

The implemented scope remains the reviewed synthetic banking workflow. Desktop
adapters, arbitrary website discovery, OS-level input locking, and compiling
human-assisted actions into a model-only capability are outside this version.

## Recorded acceptance result

The corrected fresh run passed **349 tests**, **40 genuine-artifact replay/handoff
checks**, and **eight real CLI scenarios**. Read [the verified report](../evidence/phase9-verified/README.md).
The [first failed attempt](../evidence/phase9/README.md) remains available with its
original source snapshot and failed test outcome. Its fixture-dependent test setup
was corrected before the new independent run; no runtime success was fabricated.

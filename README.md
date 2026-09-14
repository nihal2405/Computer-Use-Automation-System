# Computer-Use Automation System

Learn a UI workflow with a real model, save it as a typed capability, and replay
it without model decisions. The working example searches a synthetic banking
member, opens their accounts and reads the savings balance. Blocked interactive
runs can transfer the same browser to a local operator and verify safe resume.

Genuine Gemini discovery and model-free second-member replay are preserved in
[evidence/phase7](evidence/phase7/README.md). A separate successful manual handoff
is in [evidence/phase8](evidence/phase8/README.md). The [acceptance guide](docs/acceptance.md)
provides the complete reviewer path, coverage map and reproducibility limits.
Fresh-environment acceptance passed **349 tests**, **40 genuine-artifact replay/handoff
checks**, and **eight real CLI scenarios**. See [the results](evidence/phase9-verified/README.md).
The implementation is published on [GitHub](https://github.com/nihal2405/Computer-Use-Automation-System).
The [post-commit review](evidence/post-commit-review.json) records 349 passing tests
on the release implementation and its credential scan.
Nothing has been emailed or submitted.

## Setup

Use Python 3.13 and [uv](https://docs.astral.sh/uv/getting-started/installation/)
0.9.13 or newer. From the repository root:

```bash
uv sync --locked
uv run --locked python -m playwright install chromium
uv run --locked computer-use validate-config
uv run --locked python -m pytest -q
```

The lock records exact dependencies. Tested platform: macOS arm64, Python 3.13.0,
Playwright 1.62.0 and Chromium 151.0.7922.34. Other platforms are unverified.
Initial setup may download packages, Python and Chromium. Offline tests need
only loopback servers and Chromium, with no model key or external model service.
See [environment setup](docs/environment.md) for versions and platform notes.

## Start the target

```bash
uv run --locked python -m mock_app
```

Keep that terminal running. Open [the synthetic bank](http://127.0.0.1:8000).
Member `1001` has `1250.75 USD`; member `2002` has `8040.20 USD`. All data is
synthetic. Search, open the member and select **Accounts**. Demo controls expose
not-found, invalid input, slow loading, permission denial, session expiry,
application error and an unexpected dialog. See [the app guide](mock_app/README.md).

## Genuine discovery, then replay its generated artifact

Only **discovery** requires live model access and may incur provider charges.
The default provider is Gemini 3.6 Flash. Put `GEMINI_API_KEY` in the ignored `.env`
file; create it from `.env.example` only if it does not already exist. Never
commit the key. OpenAI is also supported with `OPENAI_API_KEY` and a corresponding
provider/model change in `config/discovery.yaml`. See [discovery configuration](docs/discovery.md).

With the mock server running, this shell command captures only the successful
artifact path in memory and replays that exact artifact for the other member:

```bash
artifact_path="$(uv run --locked computer-use discover \
  --goal "Read the requested member's savings balance and currency" \
  --inputs '{"member_id":"1001"}' --headless | \
  python3 -c 'import json,sys; d=json.load(sys.stdin); p=d.get("artifact"); sys.exit("Discovery produced no artifact") if not p else print(p)')" && \
uv run --locked python scripts/replay_without_model.py "$artifact_path" \
  --inputs '{"member_id":"2002"}' --headless
```

For the full discovery result on screen, run the `computer-use discover` command
without the pipe. A failed model call produces a failure, never a fixture passed
off as discovery. Do not redirect raw result output into a shared evidence file;
use the executor's sanitized diagnostics under `runs/`.

## Replay without a model key

Use the preserved genuine artifact while the mock server runs:

```bash
uv run --locked python scripts/replay_without_model.py evidence/phase7/capability.json \
  --inputs '{"member_id":"2002"}' --headless
uv run --locked python scripts/replay_without_model.py evidence/phase7/capability.json \
  --inputs '{"member_id":"9999"}' --headless
```

The first returns `8040.20 USD`, a verified checkpoint and exit code 0. The second
returns `member_not_found`, no outputs and exit code 2. Hard failures use exit
code 1. The wrapper removes API-key variables and blocks model/discovery and
mock-app imports in the replay process. Automation obtains outputs through the UI;
the separate mock server is the only process that owns the synthetic data.

Ordinary replay is also available as `computer-use replay PATH --inputs JSON`.
The hand-authored `tests/fixtures/read_savings_balance.json` is labelled as a
**development fixture**, separate from the genuine generated capability.

## Human takeover demo

```bash
uv run --locked python scripts/handoff_demo.py
```

This command needs no model key and starts its own synthetic bank on an available
port. Open the printed operator URL. Select **Take control**, acknowledge the
unexpected dialog in the existing Chromium window, then select **Verify and
resume**. The terminal reports the result; the browser and servers then close.

For an existing server, add `--interactive` to replay or discovery. Omit
`--headless`; an operator needs the visible window. **Cancel run** ends the run.
The default operator timeout is 900 seconds. See [handoff](docs/handoff.md) for
capture, ownership, deadlines, unexpected-page handling and resume restrictions.

## Reproduce acceptance in a clean environment

```bash
python3 scripts/acceptance.py --output runs/acceptance-review
```

Use a new output directory each time. This creates a credential-free source copy
and fresh locked virtual environment, runs the full test suite, applies replay
and handoff tests to the genuine artifact, and captures eight real CLI scenarios.
It preserves hashes, sanitized diagnostics and stage/test outcomes. Failed
attempts remain failures; output directories are never overwritten. Downloads and
the browser cache may be reused on the same host. This is not a fresh OS or Git
clone. The original `.venv` is unchanged. See [acceptance](docs/acceptance.md).

## Design, configuration and evidence

- [REPORT.md](REPORT.md): concise design under the seven assignment headings.
- `src/computer_use/`: contracts, discovery/compiler, replay, shared executor,
  policy/redaction, browser sessions, operator UI and evidence storage.
- `config/settings.yaml`: active run/step bounds and output directories.
- `config/targets/mock_bank.yaml`: target identity, compatibility and entry URL.
- `config/policy.yaml`: default-deny operations, controls and request boundaries.
- `config/discovery.yaml` and `config/tasks/`: model and reviewed task contracts.
- [Evidence index](evidence/README.md): genuine discovery, replay, manual handoff
  and acceptance examples with provenance and source/artifact hashes.
- [Contracts](docs/contracts.md), [browser sessions](docs/browser-sessions.md),
  [safety](docs/safety-executor.md) and [replay](docs/replay.md): implementation details.

`computer-use status` describes implemented features; it is not a fresh test run.
Safety assumes a cooperating local application and operator. This version supports
the reviewed banking workflow, not arbitrary websites or native desktop control.
Human-assisted discovery can return verified outputs but does not compile a
model-only artifact from unrecorded human actions. The operator UI is loopback-only,
not a production multi-user console. Credentials, raw traces, browser profiles and
runtime outputs are ignored by Git; only inspected sanitized evidence is retained.

GitHub publication is complete. Email submission remains a separate action.
[Delivery preparation](docs/delivery.md) records the current state.

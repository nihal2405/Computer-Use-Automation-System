# Model discovery and capability generation

Discovery uses a real provider to choose the next action from live UI observations.
The same executor used by replay validates ownership, policy, target resolution,
deadlines and checkpoints. Model claims of completion never bypass these checks.

## Configure a provider

The project supports OpenAI Responses and Gemini's OpenAI-compatible Chat
Completions endpoint through the locked OpenAI Python SDK. The configured default
is Gemini 3.6 Flash. Settings live in `config/discovery.yaml`:

```yaml
provider: gemini
model: gemini-3.6-flash
reasoning_effort: low
request_timeout_seconds: 30
max_output_tokens: 2500
```

Put `GEMINI_API_KEY=your_key` in the project-root `.env` file. To use OpenAI instead,
set `provider: openai`, `model: gpt-4.1-mini-2025-04-14`, and configure
`OPENAI_API_KEY`. An environment variable takes precedence over `.env`. A missing
provider key stops before browser startup. Keys never cross provider boundaries,
and there is no automatic provider fallback. `.env` is ignored by Git; the example
file contains only empty fields.

Google may list older models while denying generation access to new users.
A direct request with the configured key returned HTTP 404 for Gemini 2.5 Flash
and named Gemini 3.6 Flash as its replacement. The default follows that guidance;
historical Phase 7 evidence retains the model actually used at the time.
Gemini 3 requires reasoning enabled, so use `low` rather than `none`.
The [latest demo evidence](../evidence/latest-demo/README.md) records successful
discovery after this configuration update and replay of the new artifact for a
different member. Its model attribution and historical-source limits are explicit.

The model endpoint is fixed in code for each provider. Browser allowlists do not
grant access to model services: the separate provider client sends only the
discovery request. SDK network retries are disabled. Authentication, quota,
transport failures and timeouts stop the run with sanitized diagnostics.

The implementation follows [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [Google's OpenAI compatibility guide](https://ai.google.dev/gemini-api/docs/openai).
Both providers receive a JSON schema; responses are independently validated with
Pydantic. Refusals, incomplete output, invalid JSON, unknown commands and malformed
actions are rejected. The SDK does not execute browser tools itself.

## Run discovery, then replay

Start the target in one terminal:

```bash
uv run --locked python -m mock_app
```

In another terminal, discover using the first member:

```bash
uv run --locked computer-use discover --inputs '{"member_id":"1001"}' --headless
```

The command reports the run result, number of model responses, and an artifact
path only after verified completion and successful storage. Use that returned
path for the second member:

```bash
uv run --locked computer-use replay artifacts/RETURNED-ARTIFACT-ID.json \
  --inputs '{"member_id":"2002"}' --headless
```

Replace the placeholder path with the actual `artifact` field from discovery.
Replay never imports a model client and needs no API key. Both commands use exit
code 0 for success, 2 for a declared business outcome and 1 for failure.
The authorized caller sees extracted values on stdout; persisted diagnostics
redact those values. Batch commands close their browsers when they return.

`--task` selects a reviewed task JSON file; the default is
`config/tasks/read_savings_balance.json`. `--project` selects the configuration
root, including target URL. `--goal` overrides goal text within that task's
declared outputs, checkpoint and policy. It cannot grant new permissions.

## What the model learns

The task file defines a goal, typed inputs/outputs, reviewed output targets,
compatibility, completion checkpoint, business outcomes and safe recovery rules.
It contains **no ordered steps**. Discovery does not read the development artifact
or import mock banking data.

The controller opens the configured entry page, then repeatedly observes, asks
the model for one decision and executes that decision. It provides an unordered
action vocabulary from trusted policy, with live presence/enabled/condition flags
and a boolean indicating whether the search field matches its input. The model
chooses the sequence. Each chosen action is checked again immediately before use.

This is discovery of a sequence within a reviewed banking control vocabulary.
It does not autonomously invent arbitrary locators or learn a completely unknown
application. Approved labels and selectors are supplied by policy. The model sees
input references such as `inputs.member_id`, never the identifier's value. It sees
which outputs were collected, never their values. Names, balances, field contents
and arbitrary page text are excluded from model prompts. Operator-provided goal
text and reviewed control descriptions are sent to the configured provider.

## Stopping and compilation

The controller enforces total elapsed time (including model calls), step limits,
bounded invalid-response attempts, and repeated-state detection. Its fingerprint
includes visible control states, filled flags and collected output names. Repeated
states beyond `max_no_progress_steps` produce `no_progress`, including cycles that
return to an earlier state. Unknown UI states, unsafe actions and explicit model
intervention requests pause execution. Known loading states use bounded wait-only
recovery; clicks and submissions are never retried by recovery code.

When all outputs are read, or the model requests `complete`, code checks all extracted output types and executes the trusted
final checkpoint through the shared executor. It then compiles only successfully
executed steps. Read outputs cannot be declared twice or extracted from another
output's target. Mutations after extraction are rejected to avoid stale results.

The recorder restores parameter references from the exact matching reviewed
action template. It does not globally replace strings matching the example input.
The compiled artifact includes schema/capability versions, the observed target
version, successful steps, typed contracts, checkpoint and exception rules. It
passes replay preflight and sanitized export before success is reported. Files
have unique immutable names; the reviewed task controls capability versioning.

Real provider runs use `provenance: llm_discovery` and preserve the generated
`discovery_run_id` for correlation with run evidence. Test doubles always produce
`development_fixture` artifacts. Provenance fields alone are not proof of a real
model call; correlated run events are required.

Runs record sanitized model-request/response events, rejected responses, actions,
checkpoint results, recovery, artifact creation and terminal results. Raw model
messages, arbitrary explanations and credentials are not persisted. Provider
response IDs and descriptions are pseudonymized in diagnostics. A failure emits
an intervention when a live session can be paused; the Python context retains
that session until exit. `--interactive` adds operator controls, human-action
capture, and verified resume; see [handoff](handoff.md). Human-assisted completion
returns fresh verified outputs with `human_assisted: true` and does not compile
an artifact from the incomplete model-only action sequence.

## Verification

```bash
uv run --locked python -m pytest -q \
  tests/unit/test_discovery_contracts.py tests/integration/test_discovery.py
uv run --locked python -m pytest -q
```

The offline checks cover both provider request formats, credential isolation,
schema rejection, refusals, timeouts, policy denial, no-progress, invalid outputs,
false completion, recovery exhaustion, session/app errors, cancellation,
persistence failure, parameter binding, and replay of compiled test workflows.
These tests make no billable model calls and do not replace the genuine run.

The [latest demo](../evidence/latest-demo/README.md) preserves discovery and replay
with the current provider configuration. To run replay checks on its artifact:

```bash
REPLAY_TEST_ARTIFACT=evidence/latest-demo/capability.json \
  uv run --locked python -m pytest tests/integration/test_replay.py -q
```

These checks cover both inputs, exceptional outcomes, exhaustion, failed
checkpoints, typed outputs, ownership, persistence, and the model-disabled CLI.

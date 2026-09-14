# Component contracts

Pydantic models in `src/computer_use/schemas/` define the data exchanged between
discovery, replay, the executor, and handoff. I kept these separate from the
browser driver so the same saved workflow can be validated before a browser starts.

## Validate a capability

```bash
uv run --locked computer-use validate-capability evidence/latest-demo/capability.json \
  --inputs '{"member_id":"1001"}' --target tests/fixtures/mock_bank_identity.json
```

This checks the artifact, inputs, and target identity without executing actions.
The validator and replay share the same loader: duplicate JSON keys, files over
1 MiB, malformed fields, and unsupported versions are rejected. Exit code 2 means
validation failed. Error output omits submitted values.

## Actions and targets

There are six actions: `navigate`, `fill`, `click`, `read`, `wait`, and
`verify`. Each accepts only its own fields. Navigation uses a relative path;
external URLs, query strings, fragments, and traversal are excluded.

Targets use exact role/name, label, text, or CSS matching, with an optional CSS
container scope and a rationale. The browser checks that both scope and target
match exactly one element. Coordinates and frames are not supported.

Values explicitly distinguish literals from input references:

```json
{"source": "literal", "value": "Search"}
```

```json
{"source": "input", "ref": "inputs.member_id"}
```

There is no expression evaluation. References must name a declared input and have
a type that can be bound to UI text.

## Saved workflow

A capability has a schema version, ID and capability version, provenance, compatible
target, typed inputs and outputs, ordered steps, and a success checkpoint. It can
also declare business outcomes and bounded wait recovery.

Each step has a unique ID, operation name, action, and timeout. Preconditions and
postconditions are optional. An operation name is an input to policy validation,
not permission granted by the artifact.

All declared inputs and outputs are required. Supported types are `string`,
`integer`, `boolean`, `decimal_string`, and `currency_code`. Member IDs remain
strings; balances remain fixed-point decimal strings. Currency validation checks
three uppercase letters, not membership in a currency registry.

Every output needs one read step. Missing outputs, duplicate reads, undeclared
references, and wrong types fail validation. The replay extractor converts visible
text strictly; it does not guess currency symbols or treat arbitrary text as true.

Schema version `1.0` is supported. Capability versions use three numeric parts;
app versions are separate strings matched against the supported list.
`development_fixture` artifacts have no discovery run ID; `llm_discovery`
artifacts require one. Correlated logs are still needed to establish provenance.

Models are frozen but nested lists and dictionaries can still be mutated.
Execution and storage boundaries revalidate and copy incoming models.

## Conditions and outcomes

Conditions are `visible`, `hidden`, and `text_equals`. The browser evaluates
them against current UI state.

- `success` requires typed outputs and `checkpoint_verified: true`.
- `business_outcome` identifies a declared result such as `member_not_found`,
  without a balance payload.
- `failure` includes a code, stopped step, expected/observed details, and optional
  evidence and intervention references.

Recovery is an intermediate action, not a fourth terminal result. The current
rule waits for slow loading within an attempt count and deadline. It never permits
repeating a click or submission.

## Observations and ownership

Observations contain target identity, run/session IDs, a sequence number, current
state, and addressable controls. Raw driver observations stay in memory; executor
projections and persisted diagnostics are redacted.

An intervention records the goal, stopped step, reason, context, and ownership.
A resolution links captured human events and the verification performed before
resume or completion.

Ownership follows `AUTOMATION_RUNNING → AWAITING_HUMAN → HUMAN_CONTROL →
RESUME_CHECK`. Inspection is allowed during resume checks; navigation, fill, and
click are blocked. Completed and failed sessions cannot restart. These records
describe legal transitions; the [session lock](browser-sessions.md) and
[handoff coordinator](handoff.md) enforce them.

Run `uv run --locked python -m pytest -q tests/unit` for contract checks.

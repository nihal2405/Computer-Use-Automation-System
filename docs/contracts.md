# Component contracts: schema version 1.0

These contracts validate the information exchanged between components. They do
not execute browser actions, enforce runtime policy, sanitize arbitrary text, or
prove that a checkpoint actually passed. The corresponding runtime components
provide the execution guarantees. [Phase 4](browser-sessions.md) implements browser
operations and ownership locking; [Phase 5](safety-executor.md) adds runtime policy
and redaction, and [Phase 6](replay.md) adds deterministic replay.

## Validate the development artifact

From the repository root:

```bash
uv run --locked computer-use validate-capability tests/fixtures/read_savings_balance.json \
  --inputs '{"member_id":"1001"}' \
  --target tests/fixtures/mock_bank_identity.json
uv run --locked python -m pytest -q tests/unit
```

The first command returns `status: valid`, `provenance: development_fixture`, and
`executed: false`. It validates structure, cross-references, supplied input types,
and target compatibility. It never starts a browser or calls a model.

Changing the member ID to a JSON number, supplying an extra input, or loading an
unsupported artifact returns exit code 2 and a generic structured error. The CLI
deliberately omits submitted values from diagnostics. Programmatic callers can
inspect validation errors in memory; they must sanitize them before persistence.

## Shared rules

Models use Pydantic with strict types and extra fields forbidden. Each contract
can be parsed with `model_validate` / `model_validate_json` and serialized with
`model_dump_json`. Models also expose `model_json_schema` for structural schemas.
Cross-field rules such as declared-reference validation still require the Python
validator; JSON Schema alone is not the entire contract.

Identifiers use lowercase letters, digits, and underscores, beginning with a
letter. Schema version `1.0` is the only accepted schema version. Capability
versions use a three-part numeric release format such as `1.0.0`; prerelease
labels are outside this initial contract. Application version strings are
separate and matched exactly against an explicit supported-version list.

Validated models have frozen fields but are not deeply immutable or security
boundaries. In-place mutations of nested lists/dictionaries must be checked again
with `Capability.model_validate(...)` at an execution or persistence boundary.
Existing model instances are revalidated by that call. Do not bypass validation
with Pydantic's trusted construction/copy mechanisms for untrusted input.

## Actions and targets

The action union accepts exactly six action kinds, selected by the `action` field:

- `navigate`: a path relative to the configured application origin, such as `/`.
- `fill`: a target and a literal text value or declared input reference.
- `click`: a target to activate.
- `read`: a target and the declared output name to populate.
- `wait`: an observable condition and a bounded timeout.
- `verify`: an observable condition to assert.

Each kind accepts only its own fields. Navigation rejects external URLs,
protocol-relative URLs, traversal, query strings, and fragments in version 1.0.
This is an intentionally narrow path contract, not a substitute for checking the
actual browser origin, redirects, and policy before/after actions.

Targets use one of four strategies: exact accessible role/name, exact label,
exact text, or CSS. Every target contains a rationale explaining the proposed
choice. An optional CSS scope limits the search to a container. CSS syntax and
the existence/uniqueness of matches are now checked by the browser adapter at runtime.
Dynamic labels/names/text can reference an input; CSS and scopes remain literal.
Raw coordinates and frame navigation are not implemented in this first schema.

Text values are explicit:

```json
{"source": "literal", "value": "Search"}
```

```json
{"source": "input", "ref": "inputs.member_id"}
```

There is no expression evaluation or arbitrary string interpolation. References
inside steps, targets, pre/postconditions, success conditions, business outcomes,
and recovery rules must all resolve to declared string-compatible inputs.

## Capability artifact

`Capability` contains identity and versions, description, provenance, target
compatibility, typed input/output declarations, ordered steps, a mandatory success
checkpoint, business-outcome rules, and bounded recovery rules.

Every step has a unique ID, an operation name describing intent, one action, and
a timeout. Optional pre/postconditions express what must be true around an action.
Operation names are metadata for policy checks; an artifact cannot grant itself
permission by claiming an operation is safe.

All declared inputs and outputs are required. Supported value types are:

- `string`: nonempty text; member IDs remain strings so leading zeros survive.
- `integer`: an integer, excluding booleans and implicit string conversion.
- `boolean`: a real boolean, excluding integer/string substitutes.
- `decimal_string`: a fixed-point decimal string such as `1250.75`; no exponent,
  currency symbol, thousands separator, NaN, or infinity.
- `currency_code`: three uppercase letters. This checks shape, not membership in
  an authoritative currency registry.

Every output must have exactly one corresponding read step. Reads cannot write
undeclared outputs or overwrite another read's output. The future extractor must
convert visible UI text to the declared output shape; no extraction runs here.

`validate_inputs` and `validate_outputs` reject missing/extra names and incorrect
types. `validate_target` checks the exact product, surface, and supported version.
Desktop identity is representable for future adapters; there is no desktop driver.

The development fixture proposes seven steps: navigate to search, fill the member
ID, submit, open the matching member, open accounts, read balance, and read currency.
Its final checkpoint checks that the account page identifies the requested member.
The fixture's operations and checkpoint are exercised against both members through
the replay engine in integration tests with model access disabled.

`provenance: development_fixture` cannot include a discovery run ID. Conversely,
`provenance: llm_discovery` requires one. These fields label intended provenance;
only correlated genuine run evidence can establish that model discovery occurred.

## Conditions, recovery, and results

Conditions are `visible`, `hidden`, or `text_equals`. Text equality accepts either
literal text or an input reference. Adapters will evaluate conditions against
current observations; schema validation does not evaluate them.

Business outcomes have a declared code and detecting condition. For example,
`member_not_found` corresponds to an explicit empty-search message. A result with
that code means the search obtained an answer, rather than the application failing.

The first recovery contract permits only `slow_loading` with `wait_for`. It
declares a trigger, a completion condition, one to three attempts, and a timeout
of 1–60,000 ms per attempt. It never authorizes a click retry. The run-wide deadline
still limits total recovery time. Unknown dialogs and other conditions must stop
or request intervention until additional reviewed recovery contracts exist.

Results are a union selected by `status`, each carrying schema version, run ID,
session ID, mode, and capability identity. Discovery can fail before a capability
exists; replay results require a capability ID and version.

- `success`: requires `checkpoint_verified: true` and outputs.
- `business_outcome`: requires a declared code, step ID, and summary, with no
  success-output payload.
- `failure`: requires a recognized failure code and diagnostic expected/observed
  state, a step ID (or null before execution), and optional evidence/intervention IDs.

`result_adapter` checks result structure. Call `capability.validate_result(...)`
to additionally check output types, known business codes/step IDs, and capability
identity/version. A recovery attempt is not a terminal result; the future executor
will emit events while trying it, then produce a result or an intervention.

The verified flag is a producer assertion, not proof. The executor must actually
check the UI before emitting success. Likewise, run/session correlations must be
checked against the live invocation by the runtime manager.

## Observations and human intervention

`Observation` contains surface identity, run/session IDs, sequence number,
sanitized location/summary, a recognized state, uniquely identified controls,
and an optional evidence reference. Controls describe concrete targets, visibility,
and enabled state. Unbound input references and browser-library objects are rejected.
Keeping input field values out of the dedicated observation fields reduces accidental
capture; arbitrary text still needs runtime redaction.

An `Intervention` carries a goal, run/session identity, optional capability
identity, stopped step, reason, diagnostic, observation, ownership snapshot, and
optional resolution. Nested run/session/step context must agree.

Control states have one defined owner:

- `AUTOMATION_RUNNING`: automation may dispatch UI actions.
- `AWAITING_HUMAN`: neither party has claimed control.
- `HUMAN_CONTROL`: the human owns the session.
- `RESUME_CHECK`: automation owns inspection/verification; action dispatch is disabled.
- `COMPLETED` and `FAILED`: no owner; terminal states cannot restart.

`ControlTransition` rejects a changed session ID, ownership mismatch, and illegal
state jumps. A human must return through `RESUME_CHECK` before automation resumes.
After a failed resume check the system can request intervention again.

A resolution records the operator, sanitized summary, actual-human-actions
evidence reference, and resume/complete/abort choice. Resume and completion require
recorded verification plus `state_verified: true`; resume alone requires a resume
step ID. The resolution must agree with the final control snapshot. The
coordinator must check that the chosen resume step belongs to the live capability,
perform real verification, and enforce ownership atomically.

The records themselves do not implement locking or takeover. The session runtime
now enforces ownership and preserves the live page through transfers. The
[handoff coordinator](handoff.md) implements event capture and verified resume.
The shared executor now redacts supported
persistence paths. Evidence references are opaque IDs;
they should point to sanitized stored evidence, never embed raw DOM/screenshots.

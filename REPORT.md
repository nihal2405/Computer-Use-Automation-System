# Architecture

**Proposed design; implementation pending.** Use one Python automation package
and a separate local mock banking application with synthetic data. The target
workflow is search → member detail → accounts → savings balance. A browser driver
will operate the UI; automation must never import mock data or retrieve balances
through application APIs.

Discovery will observe the live surface, ask a model for a typed action, and send
that action through a shared executor. Replay will load a capability and invoke
the same executor without importing or calling the model client. The executor
will check session ownership and policy before resolving and performing actions.
A session manager will retain the browser across pauses. Initial implementation
choices are Python and a Playwright browser adapter; provider selection remains
open. One process keeps the control and debugging paths small.

# Artifact schema

Use versioned JSON with separate schema and capability versions, a descriptive
identity, typed input/output contracts, compatible target metadata, ordered
actions, target descriptions, and a final success checkpoint. Each step will have
a stable ID and explicit pre/postconditions where needed. Inputs such as member
IDs will use declared parameter references rather than embedded discovery values.
The compiler will bind values using known input provenance, not global string
replacement. Artifacts must remain independent of browser-library objects and
raw model transcripts. Reject unsupported versions, undeclared parameters,
unsupported actions, and incompatible targets before executing.

Targets will prefer accessible labels and roles with an explicit scope. Missing
or ambiguous matches must fail safely. Approved target overrides belong in target
configuration and must not allow the model to broaden safety permissions.

# Determinism & error handling

Replay will execute stored steps with fixed targeting rules, bounded waits and
predefined recovery branches. No model will decide replay actions. A verified
checkpoint will precede returning the declared outputs; current UI data may
change between runs. Input validation, failure diagnostics, and output shape
validation are part of the execution contract.

Distinguish success, expected business outcomes such as member-not-found, and
hard failures carrying step, expected state, observed state, and a diagnostic
reference. Recoverable states will use bounded policies, such as waiting for a
known delayed load. Permission denial, session expiry, unknown dialogs, and
application errors need explicit handling rather than continuing blindly. Do not
retry non-idempotent actions automatically. Discovery also needs step, time, and
no-progress limits. Structured events and sanitized failure snapshots will make
both paths inspectable.

# Heterogeneity & multi-tenant

Keep observation, targeting, action, and checkpoint interfaces independent of
Playwright. The first adapter will use browser-visible state. Semantic targeting
alone does not solve non-semantic legacy markup; frame-aware scopes and approved
locators can cover some legacy web surfaces. A future desktop adapter would need
accessibility or visual targets with appropriate verification and ambiguity
handling. Desktop execution is a design extension, not an implemented claim.

Separate vendor-product capability identity from tenant entry URLs, approved
label/locator overrides, and supported application versions. Validate target
identity and workflow preconditions before replay; incompatible versions should
stop for review. Tenant credentials and browser contexts must remain isolated.
Do not build queues, distributed orchestration, or a tenant platform for this demo.

# Escalation & handoff

The intended control states are AUTOMATION_RUNNING, AWAITING_HUMAN,
HUMAN_CONTROL, RESUME_CHECK, and terminal COMPLETED/FAILED. An intervention will
include run/session identity, goal or capability, current step, stop reason, and
sanitized state. The operator will take control of the same visible browser, with
automation action dispatch disabled while human control is active.

Capture actual human interactions as redacted metadata, without recording field
contents or secrets. A resume signal will trigger observation and checkpoint
validation to determine whether the current step is complete, can safely retry,
or requires another intervention. Do not blindly advance or replay actions after
manual changes. A minimal local operator interface is sufficient; concurrent
co-browsing infrastructure is out of scope.

# Safety

The executor will enforce explicit allowed origins/routes and action types in
both discovery and replay. Unknown operations will be denied by default. The
initial workflow is read-only: risky operations such as deletion or transaction
submission will be blocked. Model suggestions and text encountered in the target
application are untrusted inputs and cannot change policy or control ownership.

Logs, artifacts, failure snapshots, and human-action capture must avoid secrets,
full PII, and raw sensitive data. Redact before persistence and minimize model
observations. Use synthetic fixtures for the demo. Runtime output is ignored by
Git; only reviewed, sanitized samples go into evidence. Ignore rules are only an
accidental-commit precaution, not an implemented redaction system. Runtime policy,
redaction, navigation checks, and takeover safety remain to be implemented and tested.

# Cuts

This initial commit establishes repository structure and design only. Discovery,
artifact validation/compilation, replay, the mock application, policy enforcement,
redaction, evidence generation, tests, and live handoff are pending. The status CLI
only reports that state. No example logs or capabilities have been fabricated.

The completed assignment must contain a thin working implementation of every
core requirement. Intended final cuts are native desktop execution, multi-tenant
infrastructure, a polished operator dashboard, and optional stretch features.
Implement contracts and the mock surface first, then shared safe execution and
replay, genuine discovery, handoff, and actual-run evidence. Revise this report
to describe tested behavior and remaining limits before submission.

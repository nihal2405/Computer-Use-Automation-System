# Architecture

This system discovers and replays a savings-balance lookup against a local Flask
bank containing synthetic members. The workflow is search, member record,
accounts, then balance and currency. Python controllers share one executor and
one Playwright/Chromium surface. Keeping orchestration in one asyncio process
makes browser lifetime and exclusive control explicit without introducing queues
or services that the demonstration does not need.

Discovery accepts a goal and reviewed target configuration. Gemini or OpenAI
returns structured actions; validation and policy run before execution. Gemini
2.5 Flash supplied six actual decisions in the preserved discovery run. The model
sees reviewed control descriptions and live visibility/state flags, with input
references instead of member values. It chooses the sequence within an approved
vocabulary; it does not discover arbitrary locators on unknown websites. This
limits generality while keeping model output and application text untrusted.

# Artifact schema

Pydantic contracts describe schema version, capability identity/version, compatible
target, typed inputs/outputs, ordered steps, locator rationale, parameter
references, success checkpoint, business outcomes, and bounded recovery rules.
The balance is a validated decimal string, avoiding binary floating-point loss.
Unknown actions, incompatible versions, missing inputs, bad references, and
undeclared outputs are rejected before execution.

Compilation includes only successful actions and restores input references from
known policy templates, never by replacing every matching string. The artifact
is independent of the transcript and has explicit provenance and a discovery run
ID. Genuine artifacts and hand-authored fixtures remain distinct. Immutable files
and SHA-256 manifests support review and correlation; provenance is not a
provider-signed attestation. Replay uses the same artifact for a different member
and reads that member's current UI values.

# Determinism & error handling

Replay binds inputs and follows recorded steps without model decisions. Exact
scoped roles/labels are preferred; reviewed CSS identifies legacy-style balance
cells. Missing or ambiguous controls fail rather than selecting the first match.
Condition-based waits share step deadlines. Success requires typed outputs and
a visible account-owner checkpoint; completed clicks alone are insufficient.

The result separates success, member-not-found, and hard failures such as denied
permission, session expiry, app errors, invalid input, and failed checkpoints.
Known loading permits bounded waits, with no repeated search submission. Exhausted
recovery stops and requests intervention. Discovery additionally limits steps,
elapsed time, invalid responses and repeated states. Model declarations cannot
supply the result. Persistence failure closes the browser instead of reporting
an unaudited success.

# Heterogeneity & multi-tenant

Controllers use a surface contract rather than Playwright objects. A desktop
adapter could resolve OS accessibility controls, with reviewed screenshot or
coordinate targeting where accessibility is absent. Legacy frames require
explicit frame scopes and separately tested navigation boundaries. Neither
adapter is implemented; silently guessing visual targets would weaken safety.

Tenant reuse would retain the capability while applying reviewed origin,
identity, locator and operation configuration for a compatible app version. Each
run already has an isolated browser context. Product/version markers and exact
route checks reject incompatible targets; markers assume a cooperating app and
are not authentication. New tenants need contract tests and policy review before
reuse. A deployed tenant registry, credential vault and cross-tenant compatibility
matrix are future infrastructure, not features claimed by this demonstration.

# Escalation & handoff

Interactive runs keep the existing browser alive and expose a token-protected
loopback operator screen with goal, stopped action, reason and sanitized context.
Ownership proceeds through AUTOMATION_RUNNING, AWAITING_HUMAN, HUMAN_CONTROL and
RESUME_CHECK. Automation dispatch is blocked during human ownership; cookies,
page and session identity survive. Trusted browser events record interaction
categories and element tags without field contents or keypress data.

Resume verifies target compatibility, the exact requested account route, owner
checkpoint and output targets. A single-use permission allows fresh output reads
and final verification without repeating navigation the operator completed.
Wrong pages remain paused. Cancel, operator deadline, closed windows and
interrupted control commands terminate safely. Human waiting has a separate
bounded budget. Human-assisted discovery may finish with verified outputs, but
cannot compile an incomplete model-only action history into a capability.

A separate manual operator run captured click, submit and navigation events,
then resumed successfully in the same session. Automated handoff tests are
labelled simulated-operator checks and are not presented as manual evidence.

# Safety

Both modes enforce default-deny origins, routes, actions and operations through
the shared executor. Actual controls, form methods and destinations are checked;
redirect destinations are checked before following. Frames, popups, background
APIs, WebSockets and downloads are blocked. A separate human-only rule permits
just the current member's CSRF-checked dialog acknowledgement. It grants no
transfer operation or general POST permission. Model or UI text cannot widen it.

Diagnostics use per-run keyed tokens for unreviewed text and mask registered
input/output values. Structural failure snapshots retain hierarchy and visibility,
not text, values, URLs, cookies or scripts. No raw screenshots or traces are saved.
Keys remain outside Git. The local operator token protects commands but does not
establish a person's identity. Browser locks gate automation; cooperative DOM
suppression cannot lock the OS, address bar or developer tools. This is a bounded
local demonstration, not a production banking security boundary.

# Cuts

The implemented vertical slice includes genuine model discovery, generated
capability reuse, deterministic outcomes, policy, redacted evidence and live human
handoff. Fresh-source acceptance installs a new locked environment, runs the full
suite, applies replay/handoff checks to the genuine artifact, and captures eight
CLI scenarios. Historical discovery and manual handoff records are preserved;
acceptance reports retain failed attempts rather than rewriting them as successes.
The reviewer commands and evidence map are in docs/acceptance.md.

The current source snapshot identifies the accepted runtime; no exact source
snapshot was captured for the older discovery run. Caches and the same macOS host
are reused, so this is not independent OS validation. Native desktop execution,
unknown-site exploration, multi-user operation, production credential management
and broad workflow repair are deliberate cuts. Next work would prioritize a
second target adapter, reviewed tenant variants and a production threat model.
Public GitHub publication is authorized after final review. Email submission
remains pending explicit user direction.

# Build checklist: computer-use automation

Build a system that learns a task through a real UI, saves a reusable workflow,
replays it without model decisions, and hands the same live session to a person
when it cannot safely continue.

Work through these phases in order. Write the relevant tests alongside each
component. Mark a box complete only when its behavior has been verified; an empty
file or a proposed design does not count as an implementation.

Checked items describe verified work. Phases 1–8 include the environment, contracts,
banking app, browser/session controls, shared executor, policy, sanitized diagnostics,
deterministic replay, genuine Gemini discovery and capability compilation.
Human takeover/resume is implemented, tested with simulated operators, and verified
in a separate manual run. See [handoff](handoff.md).
This checklist does not itself authorize publication or submission.

## 1. Establish the project and its boundaries

- [x] **Create an independent local Git repository and initial commit.**
  Why: version history lets us review changes and recover earlier work without
  including unrelated files from the computer.
- [x] **Choose the first demonstration workflow.** Search for a synthetic member,
  open their record, open accounts, and read the savings balance.
  Why: one concrete task gives every component a shared definition of success.
- [x] **Create the package layout, configuration templates, and design outline.**
  Why: explicit responsibilities help keep the UI driver, model, replay, safety,
  and human control from becoming one tightly coupled script. These are scaffolds.
- [x] **Install and record the development dependencies and setup commands.**
  Include the mock server, browser driver/browser, schema validation, configuration
  loader, and test runner. Add the chosen model dependency when discovery begins.
  Why: another developer must be able to reproduce the environment from a clean
  checkout. Record tested versions rather than relying on machine-specific installs.
  Completed: Flask, Playwright with Chromium, Pydantic, PyYAML, and pytest are
  installed in `.venv`; exact dependency versions are recorded in `uv.lock`.
  See [environment setup](environment.md). Two environment checks pass in both
  the project environment and a second fresh virtual environment.

Phase complete: the local environment is reproducible and the demo scope is clear.
Validation was on macOS arm64 with Python 3.13.0; other platforms remain untested.

## 2. Define the contracts that connect the components

- [x] **Define and validate actions and targets.** Describe actions such as fill,
  click, read, and wait, plus how each control is identified.
  Why: discovery and replay need the same limited action language, and malformed
  actions must be rejected before anything happens in the application.
- [x] **Define and validate the capability artifact.** Include schema/capability
  versions, target compatibility, typed inputs and outputs, ordered steps,
  parameter references, and a success checkpoint.
  Why: the saved workflow is the contract a caller will reuse with new inputs.
- [x] **Define observations and execution results.** Distinguish success, business
  outcomes such as member-not-found, and failures with step/expected/observed
  details. Define which conditions permit bounded recovery.
  Why: a caller needs to know whether it obtained an answer or the system could
  not obtain one. Observations give both execution modes a shared view of the UI.
- [x] **Define intervention records and control ownership states.** Include goal,
  run/session ID, stopped step, reason, sanitized context, and resolution.
  Why: human handoff needs an explicit contract from the start so browser lifetime
  and action execution can support it later.
- [x] **Test invalid and incompatible contracts.** Reject unsupported versions,
  unknown actions, missing inputs, invalid parameter references, and undeclared outputs.
  Why: loading a JSON file successfully does not mean it describes a valid workflow.

Phase complete: the hand-authored seven-step development artifact validates,
and malformed examples fail. There are 95 passing contract tests and two passing
environment checks (97 total). See [contracts](contracts.md) for fields, validation
commands, and limitations. Validation does not execute the workflow or implement
runtime policy, browser locking, redaction, discovery, or actual human takeover.

## 3. Build the synthetic banking application

- [x] **Add at least two synthetic members with different balances.**
  Why: replaying for the second member proves the workflow uses new inputs and
  reads current UI data instead of returning the discovery example's answer.
- [x] **Implement search, results, member details, and accounts screens.**
  Why: the automation needs a real multi-step interface to navigate. Keep target
  data inside the mock application; automation must obtain results through the UI.
- [x] **Add controlled exceptional states.** Include invalid input, missing member,
  slow loading, permission denial, session expiry, application error, and an
  unexpected dialog that a human can resolve.
  Why: reproducible problems let us develop and demonstrate deliberate recovery,
  failure reporting, and handoff instead of hoping those situations occur.
- [x] **Verify the screens and scenario behavior manually and with app checks.**
  Why: a broken target application can look like a broken automation system.
  Confirm the normal workflow can be completed by a person before automating it.

Phase complete: both member balances were retrieved interactively through the UI.
All seven exceptional scenarios have reproducible controls and passing app checks:
31 server tests and 16 Chromium tests, with 144 tests passing across the project.
See the [app guide](../mock_app/README.md) for commands and scenario instructions.
At that milestone the mock dialog supported manual resolution; orchestration was added in Phase 8.

## 4. Build browser interaction and session management

- [x] **Define a surface interface and implement its browser adapter.** Support
  observation, navigation, fill, click, read, wait, and checkpoint evaluation.
  Why: the rest of the system should express what to do without depending on
  browser-library objects. This also leaves a seam for future desktop support.
- [x] **Implement precise targeting.** Prefer scoped labels/roles where available;
  reject missing or ambiguous matches and document limits on legacy markup.
  Why: clicking the wrong matching control can silently produce the wrong result.
- [x] **Manage the browser independently of individual steps.** Preserve one live
  session across actions, pause, and takeover, with explicit shutdown handling.
  Why: human intervention must retain the current page and session context.
- [x] **Implement ownership checks and condition-based waits.** Only automation
  may dispatch actions while it owns the session; wait for observable conditions
  within a deadline rather than relying on arbitrary sleeps.
  Why: human and automation actions must not race, and slow pages must not cause
  premature clicks or indefinite waiting.

Phase complete: browser operations retrieve both balances and verify the member
checkpoint through the adapter. All adapter operations are blocked during human
control; resume checks permit inspection but block navigation, fill, and click.
Thirty integration tests cover targeting, deadlines, ownership races, cancellation,
session preservation/isolation, and shutdown. All 174 project tests pass.
See [browser sessions](browser-sessions.md).
The test simulates an operator on the same page; actual event capture and the full
handoff coordinator were later work at that milestone; Phase 8 implements them.

## 5. Put safety and diagnostics into the shared execution path

- [x] **Load and validate runtime, target, and policy configuration.**
  Why: allowed applications, time limits, and target differences must be explicit
  settings rather than values scattered throughout workflow code.
- [x] **Enforce a default-deny allowlist and risky-operation rules.** Check allowed
  origins, routes, actions, operations, and navigation boundaries in both modes.
  Treat model output and application text as untrusted; neither may broaden policy.
  Why: permission must be enforced by code even when a model suggests an unsafe action.
- [x] **Build redaction before storing observations or actions.** Cover inputs,
  errors, model explanations, artifacts, failure snapshots, and human-event metadata.
  Why: logs and screenshots can expose the same sensitive information as the UI.
- [x] **Create structured events and sanitized failure evidence.** Include run ID,
  mode, step, action, policy decision, checkpoint result, retries, and control changes;
  capture a sanitized DOM snapshot or another richer signal on failure.
  Why: these records let us explain why a run stopped and demonstrate what happened.
- [x] **Connect all actions through one executor and test its boundaries.** Enforce
  ownership, policy, target resolution, execution, and event recording in one path.
  Why: discovery and replay must receive identical protections. Test denied
  navigation, risky operations, ambiguous controls, and sensitive-data persistence.

Phase complete: prohibited controls, routes, requests, and redirect destinations
are blocked; supported diagnostic and artifact writes are sanitized first. Both
mode labels use the same executor. All 230 tests pass, including 23 safety unit
checks and 33 live-browser safety checks. See [safety and diagnostics](safety-executor.md).
At that milestone, discovery, replay, human-event capture, and submission evidence
remained later phases. Replay is now completed below.

## 6. Implement deterministic replay first

- [x] **Create a clearly labelled, hand-authored development artifact.**
  Why: it lets us test the execution machinery before depending on model behavior.
  This fixture is not evidence of genuine discovery.
- [x] **Load the artifact, validate inputs, and bind parameters.**
  Why: a caller must be able to supply another member ID without editing the workflow.
- [x] **Execute steps, verify checkpoints, and validate extracted outputs.**
  Why: completing clicks is not proof of success; the intended result must actually
  be visible and returned in the declared shape.
- [x] **Handle business outcomes, bounded recovery, and hard failures.** Use known
  rules for waits/retries, check whether repeating an action is safe, and emit an
  intervention when recovery cannot safely continue.
  Why: stable interfaces still encounter real runtime problems and unknown states.
- [x] **Test replay using different inputs with model access disabled.** Include
  not-found, recovery exhaustion, failed checkpoints, and app/permission errors.
  Why: this proves reuse, honest result reporting, and independence from LLM decisions.

Phase complete: the same development artifact retrieves `1250.75 USD` for `1001`
and `8040.20 USD` for `2002` through Chromium, including a model-disabled CLI run.
All 282 tests pass, including 52 replay checks covering the exceptional outcomes.
See [replay](replay.md) for commands, recovery limits, and sanitized interventions.
The Python context preserves paused sessions; the batch CLI closes its browser.
Genuine discovery and full takeover/resume are implemented in Phases 7 and 8 below.

## 7. Add genuine LLM discovery and capability generation

- [x] **Choose and configure a model provider with structured action responses.**
  Validate responses against the action contract and keep credentials outside Git.
  Why: discovery needs a real model connection while execution still requires
  predictable, checked commands.
- [x] **Implement the observe → decide → act loop.** Accept a goal and target,
  provide suitable UI observations, and route model-selected actions through the executor.
  Why: the system must discover how to complete a task from the live interface.
- [x] **Add verified completion and stopping conditions.** Enforce maximum steps,
  elapsed time, no-progress detection, invalid-response handling, and intervention routing.
  Why: a model must not loop forever or declare completion without observable evidence.
- [x] **Record successful actions and compile a parameterized capability.** Use
  known input bindings rather than replacing matching strings indiscriminately;
  validate the compiled artifact before versioned storage.
  Why: the successful run must become a reusable workflow independent of the model transcript.
- [x] **Run real discovery, then replay its generated artifact for another member.**
  Why: this connects the two halves of the project and proves the artifact learned
  during discovery actually works in deterministic execution.

Phase complete: Gemini 2.5 Flash supplied six real model decisions for member `1001`;
the controller verified `1250.75 USD` and compiled a parameterized capability.
That same artifact returned `8040.20 USD` for `2002` in a process with model imports
blocked and API keys removed. All 326 tests pass, and all 21 replay integration
checks also pass against the genuine artifact. See [discovery](discovery.md) and
[sanitized run evidence](../evidence/phase7/README.md). Test doubles remain labelled
development fixtures. Discovery learns a sequence within the reviewed control vocabulary;
Phase 8 adds the full human takeover/resume coordinator.

## 8. Complete human takeover and safe resume

- [x] **Route a blocked run to a minimal local operator interface.** Show the goal,
  step, reason, and sanitized context, with explicit takeover and resume controls.
  Why: someone must be able to understand and resolve the intervention request.
- [x] **Transfer exclusive control of the existing browser to the human.**
  Why: a new browser would lose the exact problem state; concurrent automated
  actions could interfere with the person's work.
- [x] **Capture actual human interactions with redaction.**
  Why: a continuous record must explain what changed during takeover without
  persisting passwords, field contents, or other sensitive values unnecessarily.
- [x] **Inspect state before resuming and test the full handoff.** Cover a human
  resolving the obstacle, already completing the interrupted step, navigating to
  an unexpected page, and cancelling the run.
  Why: resuming blindly can repeat completed work or act on the wrong page.

Phase complete: all 345 tests pass, including 19 Chromium handoff cases. A separate
manual operator run paused at the dialog, captured click/submit/navigation events,
verified the returned account state, and resumed in the same session to return
`8040.20 USD`. See [handoff](handoff.md) for commands and boundaries, and
[preserved manual evidence](../evidence/phase8/README.md).

## 9. Integrate, validate, and capture real evidence

- [x] **Provide documented commands for the mock app, discovery, replay, and handoff.**
  Why: the system needs a repeatable entry point that a reviewer can use without
  manually connecting internal modules.
- [x] **Run the integrated acceptance checks from a clean environment.** Verify
  UI-only access, generated artifact reuse, model-free replay, error taxonomy,
  safety enforcement, redaction, and exclusive same-session takeover.
  Why: individually working components can still fail when combined.
- [x] **Collect and inspect sanitized evidence from real executions.** Save a
  generated capability and discovery/replay logs, plus not-found and handoff examples
  and a richer failure diagnostic. Record relevant source/artifact/target versions.
  Why: the assignment requires observable proof of genuine discovery and replay;
  correlated records let another person understand and reproduce it.

Phase complete: a fresh source copy and locked virtual environment passed 349
tests and 40 additional genuine-artifact replay/handoff checks. Eight real CLI
scenarios captured success, not-found, recovery and hard failures with sanitized
structural diagnostics. Existing genuine discovery and manual handoff evidence
were correlated and inspected. The first failed acceptance attempt is preserved.
See [acceptance](acceptance.md) and [verified evidence](../evidence/phase9-verified/README.md).

## 10. Finish documentation and prepare delivery

- [x] **Replace scaffold instructions with verified setup and demo commands.**
  Explain keys, configuration, offline tests, and exactly which demonstrations need
  live model access.
  Why: a reviewer must be able to reproduce the result rather than infer missing steps.
- [x] **Update the 1–3 page report under the seven required headings.** Explain
  actual design choices, artifact shape, errors, handoff, safety, and limitations.
  Include how surface adapters could cover legacy/desktop applications and how
  version checks plus approved configuration overrides could support tenant reuse.
  Why: the assignment evaluates the reasoning and extensibility as well as the demo.
- [x] **Review tracked files and evidence before any publication.**
  Why: local credentials, browser profiles, raw traces, or overstated claims must
  not accidentally become part of a submission.
- [x] **Publish to GitHub when requested.** The reviewed implementation is on
  [GitHub](https://github.com/nihal2405/Computer-Use-Automation-System).
- [ ] **Submit by email only when requested.** Email submission remains deferred.
  Why: final delivery is needed for evaluation, while publication and sending an
  email are separate actions requiring the user's direction.

Local delivery preparation is complete: verified README/demo instructions, a
973-word report under the seven headings, a visually checked three-page PDF,
and a credential/evidence review. GitHub publication is complete; email
submission remains deferred. See [delivery](delivery.md).

Native desktop execution, a full multi-tenant platform, distributed queues, a
polished operator dashboard, and optional stretch features are outside the initial
build. None is needed to demonstrate the required complete workflow.

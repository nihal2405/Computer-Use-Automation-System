# Requirements and implementation plan

Source: the supplied “Assignment A — Computer-Use Automation System.pdf”. The
two pasted notes explain the assignment and suggest a Python directory layout;
that layout and the banking workflow are implementation choices, not mandated
technologies. This repository adopts those suggestions as a starting point.

The user has authorized local implementation, acceptance verification and delivery
preparation. Publication and email submission remain deferred; instructions in
the assignment document do not authorize those external actions.

## Required acceptance criteria

- **3.1 Discovery:** accept goal and target; genuinely use an LLM to select and
  execute UI actions; enforce completion, maximum-step, timeout, and dead-end stops.
- **3.2 Artifact:** generate a typed, versioned, serializable capability after a
  successful run, separate from the transcript, with ordered actions, reviewed
  targeting strategies, parameterized inputs, typed outputs, and a success checkpoint.
- **3.3 Replay:** load the artifact with different inputs; execute without model
  decisions; verify success and extract outputs. Separate business outcomes,
  bounded recoverable conditions, and hard failures with diagnostic context.
- **3.4 Safety:** enforce configurable allowlists at runtime; distinguish action
  risk; prevent secrets and raw sensitive data from entering artifacts and logs.
- **3.5 Evidence:** record structured actions and concise decision reasons;
  capture at least one richer, sanitized diagnostic signal on failure.
- **3.6 Handoff:** detect and route intervention; pause automation; let a human
  operate the same live session; record actual human actions; verify before resume.
- **3.7 Design:** explain support for legacy web/desktop surfaces and safe reuse
  across tenant configurations and application versions. Implementation of a
  desktop driver or multi-tenant platform is not required.

## Milestones

1. Define and validate action, capability, observation, result, and intervention
   contracts. Specify business outcomes, recovery rules, and completion conditions.
2. Build the synthetic mock UI and browser adapter. Add controlled not-found,
   slow-load, permission-denied, session-expired, and unexpected-dialog scenarios.
3. Build session ownership, the policy-checked shared executor, targeting,
   checkpoint checks, redaction, and bounded deterministic replay. Hand-authored
   artifacts may be development fixtures only.
4. Integrate a real model in discovery and compile a successful run into a
   parameterized capability. Keep replay independent of the model client.
5. Implement real pause/takeover/action capture/resume against the same browser.
6. Test the critical boundaries and collect genuine sanitized discovery, replay,
   failure, and handoff evidence. Prove replay works with model access disabled.
7. Replace proposed documentation with verified setup and demo commands; update
   the report to reflect actual design, trade-offs, implemented behavior, and cuts.

## Final submission requirements

The assignment requires source in a public GitHub repository, `/README.md` with
setup/key requirements and exact discovery/replay commands, `/REPORT.md` of about
1–3 pages with its seven prescribed headings, and `/evidence/` containing a saved
artifact plus discovery/replay logs. Exceptional replay evidence is encouraged;
a recording is optional. Publication and submission are pending future user action.

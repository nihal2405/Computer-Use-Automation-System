# Build checklist

This is the completion checklist for the assignment. Component details live in
the linked guides; historical test results remain with their original evidence.

- [x] Create a standalone repository and lock the development environment.
  [Setup](environment.md)
- [x] Define actions, targets, capabilities, observations, results, and ownership
  records. Reject malformed or incompatible contracts. [Contracts](contracts.md)
- [x] Build the synthetic bank with two members and controlled error scenarios.
  [Mock app](../mock_app/README.md)
- [x] Implement browser operations, exact targeting, condition waits, and session
  ownership. [Browser sessions](browser-sessions.md)
- [x] Route both execution modes through policy, redaction, and diagnostic storage.
  [Shared executor](safety-executor.md)
- [x] Implement deterministic replay and verify another member's current UI values.
  [Replay](replay.md)
- [x] Connect a real model, run discovery, and compile a reusable artifact.
  [Discovery](discovery.md)
- [x] Support manual control of the existing browser and verified resume.
  [Handoff](handoff.md)
- [x] Run fresh-environment acceptance and retain both failed and successful
  attempts. [Acceptance evidence](../evidence/phase9-verified/README.md)
- [x] Verify the replacement-model configuration with a new discovery and replay,
  and collect manual screenshots. [Latest demo](../evidence/latest-demo/README.md)
- [x] Write setup instructions, the design report, and evidence notes.
- [x] Publish the reviewed files to GitHub.
- [ ] Email the repository link according to the assignment's submission instructions.

The first extensions I would consider are a second read-only workflow and a second
target adapter. Transfers, account changes, supervisor approval, and production
tenant infrastructure need separate design and testing; they are outside this
submission.

# Assignment scope

The source requirements are in **Assignment A - Computer-Use Automation System**.
The Python layout and banking example came from the accompanying notes; they are
implementation choices rather than required technologies.

The project demonstrates one complete workflow: look up a synthetic member's
savings balance. These are the requirements it needs to meet:

- **3.1 Discovery:** accept a goal and target, use a real LLM to choose UI actions,
  and stop on completion, time limits, step limits, or lack of progress.
  [Discovery guide](discovery.md)
- **3.2 Capability generation:** save a typed, versioned workflow with parameterized
  inputs, ordered actions, targeting information, outputs, and a checkpoint.
  [Contracts](contracts.md)
- **3.3 Replay:** execute that artifact with different inputs and no model decisions.
  Separate business outcomes, bounded recovery, and failures. [Replay guide](replay.md)
- **3.4 Safety:** enforce configurable allowlists and operation restrictions in both
  modes; redact inputs, outputs, and sensitive text before persistence.
  [Shared executor](safety-executor.md)
- **3.5 Diagnostics:** record actions and outcomes, with a richer signal on failure.
  This implementation uses sanitized DOM structure. [Evidence index](../evidence/README.md)
- **3.6 Handoff:** retain the existing browser, transfer control to a person, record
  interactions, and verify the state before resuming. [Handoff guide](handoff.md)
- **3.7 Design:** explain how adapters and configuration could support legacy
  applications, desktop surfaces, tenant differences, and app versions.
  [Report](../REPORT.md#heterogeneity--multi-tenant) and [browser sessions](browser-sessions.md)

The assignment does not require seven banking capabilities, a desktop driver, or
a deployed multi-tenant platform.

## Delivery

The submission consists of a public GitHub repository, setup and demo commands
in the root README, a 1-3 page report under the seven required headings, and
an evidence folder containing a generated capability and discovery/replay logs.
A recording is optional.

[Latest evidence](../evidence/latest-demo/README.md) covers discovery,
second-member replay, and a separate manual handoff.

See [environment setup](environment.md) for installation, the
[mock app guide](../mock_app/README.md) for scenarios, and the
[acceptance guide](acceptance.md) for reproducible checks.

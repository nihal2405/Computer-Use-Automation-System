# Assignment scope

The source requirements are in **Assignment A - Computer-Use Automation System**.
The Python layout and banking example came from the accompanying notes; they are
implementation choices rather than required technologies.

The project demonstrates one complete workflow: look up a synthetic member's
savings balance. These are the requirements it needs to meet:

- **Discovery:** accept a goal and target, use a real LLM to choose UI actions,
  and stop on completion, time limits, step limits, or lack of progress.
- **Capability generation:** save a typed, versioned workflow with parameterized
  inputs, ordered actions, targeting information, outputs, and a checkpoint.
- **Replay:** execute that artifact with different inputs and no model decisions.
  Separate business outcomes, bounded recovery, and failures.
- **Safety:** enforce configurable allowlists and operation restrictions in both
  modes; redact inputs, outputs, and sensitive text before persistence.
- **Diagnostics:** record actions and outcomes, with a richer signal on failure.
  This implementation uses sanitized DOM structure.
- **Handoff:** retain the existing browser, transfer control to a person, record
  interactions, and verify the state before resuming.
- **Design:** explain how adapters and configuration could support legacy
  applications, desktop surfaces, tenant differences, and app versions.

The assignment does not require seven banking capabilities, a desktop driver, or
a deployed multi-tenant platform.

## Delivery

The submission consists of a public GitHub repository, setup and demo commands
in the root README, a 1-3 page report under the seven required headings, and
an evidence folder containing a generated capability and discovery/replay logs.
A recording is optional.

The [repository](https://github.com/nihal2405/Computer-Use-Automation-System) is
public. [Latest evidence](../evidence/latest-demo/README.md) covers discovery,
second-member replay, and a separate manual handoff. Email submission is still
outstanding.

See the [build checklist](build-checklist.md) for implementation status and
[acceptance guide](acceptance.md) for reproducible checks.

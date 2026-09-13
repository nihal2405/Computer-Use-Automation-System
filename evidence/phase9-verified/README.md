# Verified integrated acceptance

This independent fresh-source/fresh-virtual-environment run completed successfully
on 2026-09-13. [acceptance.json](acceptance.json) records actual stage outcomes,
package versions, platform, source and artifact hashes, and hashes of the emitted
scenario evidence. The original failed attempt remains in [phase9](../phase9/README.md).

- Full offline suite: **349 passed**, no failures or skips.
- Genuine-artifact replay and handoff suites: **40 passed**, no failures or skips.
- Real model-disabled CLI executions: **8 matched their expected outcomes**.

The standalone scenarios retain their actual result categories:

- [Successful replay](scenarios/success/summary.json): success with fresh UI output verification.
- [Not found](scenarios/not_found/summary.json): `business_outcome / member_not_found`, no balance.
- [Permission denial](scenarios/permission_denied/summary.json): `failure / permission_denied`.
- [Application error](scenarios/application_error/summary.json): `failure / application_error`.
- [Session expiry](scenarios/session_expired/summary.json): `failure / session_expired`.
- [Invalid input](scenarios/invalid_input/summary.json): `failure / invalid_input`.
- [Recovered loading](scenarios/recovered_loading/summary.json): success after bounded waiting.
- [Exhausted recovery](scenarios/recovery_exhausted/summary.json): `failure / recovery_exhausted`.

Each scenario directory contains its original sanitized events and diagnostic
files under `run/`. Failure runs include structural DOM evidence. Each search
was submitted once; no unexpected requests were recorded. `passed: true` means
the acceptance expectation matched, not that a failure became a successful lookup.
Inputs and output balances are compared in memory, not copied into this evidence.

The hosting process imports the mock application; separate replay children block
mock-app, discovery and model imports and remove API-key environment variables.
The capability is the unchanged genuine Gemini artifact from Phase 7, version
1.0.0/schema 1.0, against synthetic-bank target version 1.0.

The archive `source.tar.gz` contains the exact credential-free source snapshot
tested. The report records its SHA-256 and each source file hash. It includes
then-current documentation; delivery documentation and its PDF were finalized
afterward. Subsequent edits updated documentation, module docstrings and opaque
redaction-token encoding; final-tree verification is recorded separately in the
delivery review. The run used macOS arm64,
Python 3.13.0 and uv 0.9.13. Download/browser caches were reused; this was not a
new OS or a Git clone. No live model call or new manual operator run is claimed
here: [Phase 7](../phase7/README.md) and [Phase 8](../phase8/README.md) preserve
those separate actual executions.

Run `python3 scripts/acceptance.py --output runs/another-acceptance` to reproduce.
See [reviewer commands](../../docs/acceptance.md) and [delivery review](../../docs/delivery.md).

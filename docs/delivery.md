# Delivery

## Where to start

- [README](../README.md): installation and runnable demos.
- [Report](../REPORT.md) and [PDF](../output/pdf/design-report.pdf): the seven
  required design sections.
- [Latest demo](../evidence/latest-demo/README.md): new discovery, model-free replay,
  a separate manual handoff, and original UI screenshots.
- [Acceptance guide](acceptance.md): fresh-environment checks and their limits.
- [Evidence index](../evidence/README.md): earlier runs, including failed attempts.

## Verification history

The fresh locked environment passed 349 tests, 40 additional replay/handoff checks
against a generated capability, and eight CLI scenarios. The original failed
acceptance attempt is retained alongside the corrected run.

Implementation commit `0e0c9fe8511dfd878449936d569a87cfb0d815f0` also passed 349
tests after committing. Its [review record](../evidence/post-commit-review.json)
identifies the files and checks. That result belongs to that revision; later
changes should be checked with the current commands.

The [delivery review](../evidence/delivery-review.json) records credential and
evidence checks made before publication. API keys, browser profiles, raw traces,
and temporary files are excluded from Git. Scanning for configured credentials
does not establish that every possible secret can be detected.

## Known limits

The workflow uses a reviewed set of controls on a cooperating bank demo. It does
not implement arbitrary-site discovery, native desktop execution, a tenant
registry, or OS-level input locking. Human-assisted discovery can return verified
outputs but does not compile the person's actions into a model-only capability.

Older model runs did not capture complete source snapshots at execution time.
Their artifact hashes and run IDs support correlation, not provider-signed proof
of the source or model version.

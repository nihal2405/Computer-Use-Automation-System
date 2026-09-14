# Evidence index

The records below distinguish real model runs, real CLI executions and a manual
operator run from automated tests. Runtime inputs, balances and unreviewed text
are redacted in JSON/JSONL diagnostics; synthetic examples in documentation and
application source are labelled as synthetic.

- [Banking app walkthrough](app-walkthrough/README.md). Original screenshots of
  member search, results, profile, and accounts for synthetic member `1001`.
- [Latest demonstration](latest-demo/README.md). Six discovery responses,
  reuse of the newly generated artifact without model calls, and a separate manual
  handoff. Includes original UI screenshots containing explicitly synthetic data,
  inspected sanitized logs, provenance limitations and a file-hash manifest.

- [Phase 7: genuine discovery and replay](phase7/README.md). Gemini 2.5 Flash made
  six model decisions for the first member. The saved typed capability replayed
  for the second member with model imports blocked and keys removed. Includes
  the generated artifact, correlated run logs and artifact hash.
- [Phase 8: manual same-session handoff](phase8/README.md). A local operator
  resolved the dialog; automation verified state, reread outputs and completed
  in the same browser session. Contains value-free click/submit/navigation events,
  the original intervention, verified resolution and structural failure evidence.
- [Phase 9: preserved failed acceptance attempt](phase9/README.md). The fresh
  environment passed 349 tests; one of the 40 additional genuine-artifact tests
  failed because its setup assumed an optional fixture postcondition. The failed
  report and exact source snapshot remain unchanged.
- [Phase 9: corrected verified acceptance](phase9-verified/README.md). A separate
  fresh environment passed all 349 tests and all 40 genuine-artifact replay/handoff
  checks. Eight real CLI scenarios include not-found and hard failures, each
  retaining its actual outcome category and sanitized diagnostics.
- [Delivery review](delivery-review.json). Scope and results of the final local
  credential, archive, Git-history, documentation and evidence-integrity review.
- [Post-commit review](post-commit-review.json). The 349-test verification of
  implementation commit `0e0c9fe8511dfd878449936d569a87cfb0d815f0`.

Acceptance archives preserve credential-free source snapshots, including synthetic
mock data and test fixtures. They are reproducibility records, not raw runtime
traces. SHA-256 manifests identify source, artifacts and evidence; they are not
cryptographic attestations from a model provider. The older discovery run did not
capture a full source snapshot, a limitation retained in the documentation.

Automated handoff tests are simulated-operator checks. Model/API failure attempts
from development are retained as failed attempts.

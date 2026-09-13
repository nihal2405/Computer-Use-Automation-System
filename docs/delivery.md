# Local delivery preparation

The implementation, reviewer instructions, design report and inspected evidence
are prepared locally. Public GitHub publication is now authorized and follows the
final commit review. Email submission has not been requested or performed.

## Prepared files

- [README.md](../README.md): verified installation, mock app, genuine discovery,
  replay of the newly generated artifact, key-free replay, human takeover and tests.
- [REPORT.md](../REPORT.md): 973-word design report under the seven exact assignment
  headings. The matching [printable report](../output/pdf/design-report.pdf) is
  three pages and was rendered and visually checked for clipping and legibility.
- [Acceptance guide](acceptance.md): repeatable commands, exit codes, model-service
  requirements, coverage and limits of clean-environment verification.
- [Evidence index](../evidence/README.md): genuine discovery, second-member replay,
  manual handoff, not-found, failures, recovery, structural snapshots and manifests.

## Verification and file review

The fresh locked environment passed 349 tests and all 40 additional replay/handoff
checks against the genuine artifact. Eight standalone CLI scenarios matched their
expected outcomes. Both the failed first acceptance attempt and the successful
corrected attempt are preserved; see [the acceptance result](../evidence/phase9-verified/README.md).

The review checks tracked files, prospective untracked delivery files, committed
Git blobs and source archives against the configured API-key values. `.env` is
ignored; credentials, browser profiles, runtime logs, traces and temporary render
files are excluded from the prospective Git file set. The final review record
is [delivery-review.json](../evidence/delivery-review.json). This is a scoped
credential/evidence review, not a comprehensive security assessment or a claim
that arbitrary sensitive information can always be detected automatically.

The acceptance source archive and file hashes identify the fresh-environment
snapshot that was tested. Final packaging edits update documentation, module
docstrings and redaction-token encoding; a post-commit review records verification
of the final implementation tree separately.

## Publication state

- Public GitHub repository creation and push are authorized but not yet completed
  at the time of this preparation record.
- Sending an email or submitting the repository link remains deferred.

The user will create the GitHub repository and supply its remote URL. After the
final diff and credential review, commit and push the reviewed files. The
assignment asks for a repository link, not an emailed ZIP. A later
submission request must identify the recipient and sending account; nothing in
the assignment attachment itself authorizes sending a message.

## Limits a reviewer should know

Discovery selects a sequence within a reviewed banking-control vocabulary.
Arbitrary website exploration, native desktop execution, production tenant
infrastructure and OS-level human-input locking are unimplemented. The local
operator UI is single-user and token-protected. Human-assisted discovery returns
verified outputs without fabricating a model-only capability. Historical model
evidence lacks a full source snapshot from that older run; the current acceptance
snapshot cannot establish its exact historical revision.

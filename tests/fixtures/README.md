# Development fixtures

`read_savings_balance.json` is a hand-authored, schema-valid development workflow.
Its operations and checkpoint are exercised through the browser adapter against
both members by integration tests.
`mock_bank_identity.json` is compatible target metadata for contract checks.

Replay tests use this workflow with both members and model access disabled.
For recorded discovery output, use the artifacts under `evidence/`.
These fixtures are development inputs, not proof of a live model run.

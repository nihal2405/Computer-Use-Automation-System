# Verified Gemini discovery and deterministic replay

This is the original Gemini 2.5 Flash discovery and replay run. The artifacts and
logs are retained as captured. Later runs and acceptance results are linked below.

- [capability.json](capability.json): schema version 1.0, capability version 1.0.0,
  with `provenance: llm_discovery` and explicit invocation references.
- [manifest.json](manifest.json): provider/model, correlation IDs, artifact SHA-256,
  and the model-disabled replay conditions.
- [discovery/events.jsonl](discovery/events.jsonl): six model responses from Gemini
  2.5 Flash, action execution and verified completion. The initial navigation was
  controller bootstrap; subsequent actions were model-selected.
- [replay_success/events.jsonl](replay_success/events.jsonl): successful execution
  for the second member, with no model events.

Discovery run: `4caff583-f0a4-41e8-9236-af22520c9652`.
Replay run: `e5afc821-8704-4cf3-8b7b-bb5d4a50ac89`.
The artifact's discovery run ID matches the discovery event envelope.
Values and free-form prose are pseudonymized before storage; the original provider
response IDs are also pseudonymized. UUID-named JSON files hold sanitized terminal
diagnostics. The manifest records the actual model configuration; it is not a
cryptographic attestation from the provider.

At this milestone, the regression suite passed 326 tests. All 21 replay integration
checks were also run against this exact artifact and passed. For a repeatable second-member
demo with the local bank running:

```bash
uv run --locked python scripts/replay_without_model.py evidence/phase7/capability.json \
  --inputs '{"member_id":"2002"}' --headless
```

This entry point removes API-key environment variables and blocks model imports
before loading the CLI. Browser policy also prohibits external requests.
The subsequent [Phase 8](../phase8/README.md) adds verified manual handoff;
[Phase 9](../phase9-verified/README.md) records fresh-environment acceptance.

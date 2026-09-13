# Same-session manual handoff evidence

The live local demo completed successfully on 2026-09-13 using
`uv run --locked python scripts/handoff_demo.py`. It replayed the genuine
Gemini-generated Phase 7 capability against the synthetic bank's unexpected dialog.
No model was called during this replay.

The operator used the local UI to take control, acknowledged the bank's dialog,
and requested resume. The assistant started the demo and opened the operator
screen; it did not issue the takeover, acknowledgement, or resume actions.
This run is separate from the simulated-operator integration tests. The local
bearer token establishes access, not a verified person's identity.

Run `baec121a-c9bf-42e9-8f32-423f6226399a` retained session
`d0ea5249-b58b-4ebc-aed8-62b03f180620` through all control changes. The terminal
returned the correct synthetic savings balance after fresh UI reads and owner
verification. Persisted diagnostics retain redacted values.

In [events.jsonl](events.jsonl):

- Sequence 26 pauses the run; 28 transfers to human control.
- Sequences 29–31 capture a button click, form submission, and navigation without
  field values or page contents.
- Sequence 32 enters resume verification; 35 returns automation control.
- Sequence 36 links the verified [resolution](a40893a7-ad63-4b70-8b55-731c76673c23.json).
- Sequences 52–53 record completed control and successful completion.

The original intervention and structural failure evidence remain unchanged.
[manifest.json](manifest.json) records correlation, SHA-256 hashes, the capability,
core runtime sources, and the passing 345-test regression run (19 handoff cases).
The evidence was checked for configured API keys and synthetic field values
before copying. No API keys, operator tokens, raw screenshots, or traces are included.

See [the handoff guide](../../docs/handoff.md) to reproduce the demonstration and
understand its conservative resume rules and cooperative browser-control limits.

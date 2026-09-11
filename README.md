# Computer-Use Automation System

A local repository for the interface.ai computer-use assignment: learn a UI
workflow with an LLM, save it as a reusable capability, then replay it without
model decisions.

**Status: repository scaffold and proposed design only.** The automation, mock
application, safety controls, and human handoff are not implemented yet. No live
discovery or replay has been run, and no run evidence is claimed.

## Planned demonstration

Use a local banking mock with synthetic data to search for a member, open the
member record, navigate to accounts, and read the savings balance through the UI.
Discover the workflow for one member, then replay it for a different member.
Exercise not-found, delayed load, permission denial, and an unexpected dialog
requiring human takeover of the same browser session.

The automation must not call the mock application's data endpoints or import its
data module to obtain results. The browser must navigate and read the UI.

## Repository layout

- `src/computer_use/`: automation package, divided into schemas, discovery,
  capability compilation/storage, shared execution, replay, surfaces, sessions,
  safety, handoff, and observability. Module docstrings describe future work.
- `mock_app/`: separate target application scaffold with templates and static assets.
- `config/`: proposed runtime, safety, and target settings; not yet enforced.
- `tests/`: unit and integration acceptance plans; tests are not implemented yet.
- `artifacts/`: ignored development capabilities.
- `evidence/`: selected, sanitized evidence from actual runs, to be collected later.
- `REPORT.md`: proposed design under the assignment's seven required headings.
- `docs/requirements.md`: required behavior and implementation milestones.

## Use the scaffold

Python 3.11 or newer is the proposed baseline. The scaffold status command uses
only the standard library and requires no model API key:

```bash
PYTHONPATH=src python3 -m computer_use status
PYTHONPATH=src python3 -m computer_use --help
```

For an editable package installation:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
computer-use status
```

The packaging build backend may require network access during installation.
Runtime dependencies for the planned browser driver, mock server, schema
validation, configuration loader, and model provider will be selected and pinned
during implementation. None are required for the status command.

`.env.example` documents proposed environment variables. The scaffold does not
load `.env` or configuration files yet. Do not put real secrets in tracked files.

## Implementation and demo commands

Start with the milestones in [docs/requirements.md](docs/requirements.md).
There are deliberately no pretend discovery or replay commands: those commands
must be implemented and exercised before exact runnable examples are added here.
The final README must document model configuration, starting the target, genuine
discovery, replay with different input parameters, exceptional outcomes, and
same-session handoff. Offline fixtures must be identified as fixtures, never
presented as evidence of genuine model discovery.

## Repository scope

This repository is local only. The assignment eventually requests a public GitHub
repository with source, this README, a 1–3 page report, and real evidence. Remote
publication and submission are separate future actions.

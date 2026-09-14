# Development environment

The project uses Python, Flask, Playwright, Pydantic, PyYAML, and the OpenAI SDK.
The SDK handles both OpenAI and Gemini-compatible requests. python-dotenv loads
the selected provider's key during discovery. pytest runs the tests; Ruff checks
and formats Python code.

`pyproject.toml` declares dependencies and `uv.lock` records exact versions.
The repo selects Python 3.13 through `.python-version`. The package supports
Python 3.11 syntax, but the recorded browser runs used Python 3.13 on macOS arm64.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```bash
uv sync --locked
uv run --locked python -m playwright install chromium
uv run --locked computer-use validate-config
uv run --locked python -m pytest -q tests/environment
```

uv selects the project's `.venv`; activation is optional. The first setup may
download Python, packages, and Chromium. Playwright stores Chromium in its user
cache outside the repo. Reinstall the browser after changing Playwright versions.

Linux may also need browser system libraries:

```bash
uv run --locked python -m playwright install --with-deps chromium
```

That command can require administrator access. Linux and Windows are not covered
by the recorded macOS acceptance run.

## Keys and configuration

Replay, handoff, and offline tests need no API key. Discovery reads the selected
provider's key from the environment, falling back to the root `.env`.
Do not overwrite an existing `.env` when copying the example.

- `config/discovery.yaml`: provider, model, request timeout, and response budget.
- `config/settings.yaml`: browser visibility and execution limits.
- `config/targets/mock_bank.yaml`: target identity, version, and entry URL.
- `config/policy.yaml`: permitted origins, routes, actions, and controls.

See [discovery](discovery.md) for provider setup and [safety](safety-executor.md)
for configuration validation.

## Local checks

```bash
uv sync --locked --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m pytest -q
```

The environment tests launch a disposable local Flask server and Chromium,
perform a UI click, and reject invalid configuration. Browser tests need local
port access and permission to launch Chromium; they do not call an external model.

For a fresh source copy and virtual environment, run:

```bash
python3 scripts/acceptance.py --output runs/environment-review
```

Use a new output directory each time. Downloads and the browser cache may be
reused. This tests installation and behavior on the same host, not another OS.
[Acceptance details](acceptance.md)

## Dependency changes

Use `uv add` for a dependency and `uv lock --upgrade-package PACKAGE` to update
one deliberately. Review both the package and lockfile changes, then run the
relevant checks. Do not hand-edit `uv.lock`. Ruff is pinned so local formatting
does not depend on whichever global version happens to be installed.

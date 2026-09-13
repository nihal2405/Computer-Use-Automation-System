# Development environment

The first phase provides an isolated Python environment and a reproducible
dependency lock. Phase 2 adds [validated component contracts](contracts.md).
Phase 3 adds the [working banking UI](../mock_app/README.md); Phase 4 adds the
[browser adapter and sessions](browser-sessions.md). Phase 5 adds the
[policy-checked executor and redaction](safety-executor.md). Phase 6 adds
[deterministic replay](replay.md), and Phase 7 adds [model discovery](discovery.md).
Offline tests and replay need no API key. Genuine discovery uses a configured
OpenAI or Gemini key. Phase 8 adds [local operator handoff](handoff.md) using the
existing Flask and Playwright dependencies; its replay demo needs no model key.

## Dependencies and their purpose

- Flask 3.1.3: the local mock web server. Its dependencies include the
  Jinja2 template engine and Werkzeug development server.
- Playwright 1.62.0: browser control. Install the matching Chromium separately
  with Playwright's command; an unrelated system Chrome is not required. The
  installed Chromium and headless shell are 151.0.7922.34 (Playwright build 1234).
- Pydantic 2.13.5: validation of action, capability, and result contracts.
- PyYAML 6.0.3: reading the project's YAML configuration files.
- OpenAI SDK 2.54.0: OpenAI Responses and Gemini-compatible structured requests.
- python-dotenv 1.2.3: discovery-only loading of the ignored local `.env` file.
- pytest 9.1.1: environment checks now and application tests as components are built.
- setuptools 80.9.0: the pinned packaging backend used in an isolated build environment.

The direct dependency ranges live in `pyproject.toml`; `uv.lock` records exact
resolved versions and distribution hashes, including transitive dependencies.
Keep both files in version control. The tested package-manager version is
uv 0.9.13. Re-run the environment checks after any dependency upgrade.

## Fresh setup

Install uv using its [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
Use uv 0.9.13 or newer; use 0.9.13 to match the package-manager version tested here.
Open a terminal in the repository root, then run:

```bash
uv sync --locked
uv run --locked python -m playwright install chromium
uv run --locked python -m pytest -q
uv run --locked computer-use status
```

The project selects Python 3.13 in `.python-version`. uv uses an available
matching interpreter or downloads one. Validation on this machine uses CPython
3.13.0 on macOS arm64; the patch release is recorded, not imposed on other
developers. The package declares Python 3.11+ compatibility, but other Python
versions and operating systems have not been tested here.

The environment is stored in `.venv/`, which Git ignores. Activation is optional:
`uv run` selects it automatically. No global application packages are installed.
Do not use an unrestricted `pip install -e .` as the reproducible setup path,
because it does not enforce this lockfile or install the development group.

The first setup needs access to Python package and browser download servers.
Chromium is stored in Playwright's user cache outside the repository. The matching
full Chromium and headless browser builds are selected by the locked Playwright
release. Run the browser installation command again after upgrading Playwright.

On supported Linux systems, missing browser system libraries can be installed
with `uv run --locked python -m playwright install --with-deps chromium`; that
command may request administrator access. macOS does not need this extra step.
See the [Playwright installation documentation](https://playwright.dev/python/docs/intro).

## Verify the environment

```bash
uv sync --locked --check
uv run --locked python -m pytest -q tests/environment
uv run --locked computer-use --help
```

The environment tests start a disposable Flask server on a randomly assigned
loopback port, load and validate YAML, render an HTML template, and use a real
headless Chromium instance to click a button and check the resulting page state.
The server and browser close when the test finishes. Another test confirms that
validation rejects a configuration value of the wrong type.

These tests require permission to launch a browser process and listen on a local
port. In a restricted agent sandbox, those OS operations may require approval.
After installation they need no external website or live model service.

Verified on 2026-09-11: both tests passed in `.venv` and in a second initially
empty virtual environment. The installed CLI ran successfully in both, and
`uv sync --locked --check` reported no changes needed in the project environment.

To validate installation into an additional empty environment on macOS/Linux
without changing the working `.venv`, use:

```bash
check_env=$(mktemp -d /tmp/computer-use-env-check.XXXXXX)
UV_PROJECT_ENVIRONMENT="$check_env/venv" uv sync --locked
UV_PROJECT_ENVIRONMENT="$check_env/venv" uv run --locked python -m pytest -q tests/environment
UV_PROJECT_ENVIRONMENT="$check_env/venv" uv run --locked computer-use status
```

This installs from the existing source and lock into a fresh virtual environment;
it can reuse downloaded package and browser caches. It is not a test of a newly
cloned repository or of another operating system. The temporary environment is
disposable; the normal project environment remains `.venv`.

On 2026-09-13, integrated acceptance also passed from a separate source copy and
fresh locked environment: 349 tests, 40 genuine-artifact checks and eight real CLI
scenarios. See [acceptance](acceptance.md) for the command and explicit cache/OS limits.

## Configuration and scope

`.env.example` documents `OPENAI_API_KEY` and `GEMINI_API_KEY`; discovery loads only
the selected provider's key from the environment or project `.env`.
The shared executor now loads and validates runtime, target, and policy YAML.
Use `uv run --locked computer-use validate-config` to check them. The environment
smoke test uses disposable settings. No secret is needed to run these checks.

The first application workflow remains: synthetic member search → member details
→ accounts → savings balance. Automation must interact through that visible UI.
The component contracts validate through the CLI. Start the working banking UI
with `uv run --locked python -m mock_app`. Safety enforcement is implemented by the
shared executor, and [deterministic replay](replay.md) now uses it. The model SDK
is installed for discovery; `--interactive` enables same-session human handoff.

## Change dependencies deliberately

```bash
uv add 'package-name>=minimum-version,<next-major-version'
uv add --dev 'development-package>=minimum-version,<next-major-version'
uv lock --upgrade-package package-name
uv sync --locked
```

These are command templates; replace the placeholder names and versions. Use
`uv add` for a new dependency or `uv lock --upgrade-package` to update an existing
one. Review the lockfile diff and re-run relevant checks before recording the
change. Do not edit the generated lockfile by hand. The workflow follows
[uv's project documentation](https://docs.astral.sh/uv/guides/projects/).

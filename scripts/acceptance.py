"""Fresh-source, fresh-venv acceptance runner. Uses only stdlib before uv sync.

No secrets, existing environments, caches, or run directories enter the snapshot.
Download caches and the matching Playwright browser may be reused; this is not a
new operating system or a fresh Git clone.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("src", "mock_app", "config", "tests", "scripts", "docs")
SOURCE_FILES = (
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    ".env.example",
    "README.md",
    "REPORT.md",
    ".gitignore",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(source, destination):
    selected = [source / p for p in SOURCE_FILES]
    for directory in (*SOURCE_DIRS, "evidence/phase7", "evidence/phase8"):
        selected.extend(p for p in (source / directory).rglob("*") if p.is_file())
    hashes = {}
    for path in sorted(selected):
        relative = path.relative_to(source)
        if any(
            part.startswith(".") or part == "__pycache__" or part.endswith(".egg-info")
            for part in relative.parts[:-1]
        ):
            continue
        if path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store":
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            continue
        if path.is_symlink():
            raise ValueError("Source snapshot cannot contain symlinks")
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[str(relative)] = digest(target)
    assert not (destination / ".env").exists() and not (destination / ".venv").exists()
    return hashes


def test_summary(path):
    """Export outcomes without pytest's captured logs, fixture values or tracebacks."""
    tree = ET.parse(path)
    cases = tree.findall(".//testcase")
    failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    skipped = [c for c in cases if c.find("skipped") is not None]
    counts = {}
    for case in cases:
        # Test source identifiers are reviewed metadata; parameter values are omitted.
        name = case.attrib.get("classname", "unknown")
        counts[name] = counts.get(name, 0) + 1
    return {
        "total": len(cases),
        "failed": len(failed),
        "skipped": len(skipped),
        "passed": len(cases) - len(failed) - len(skipped),
        "by_module": counts,
        "failed_tests": [c.attrib.get("name", "unknown").split("[")[0] for c in failed],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New evidence directory; never overwritten"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = Path(tempfile.mkdtemp(prefix="computer-use-acceptance-"))
    checkout = workspace / "source"
    report = {
        "schema_version": "1.0",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "clean_environment": {
            "fresh_source_copy": True,
            "fresh_venv": True,
            "dotenv_copied": False,
            "existing_run_data_copied": False,
            "download_caches_reused": True,
            "new_os": False,
            "git_clone": False,
        },
        "platform": platform.system(),
        "architecture": platform.machine(),
        "stages": [],
    }

    def save():
        (output / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")

    save()
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.endswith("_API_KEY")
        and k
        not in {
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            "UV_PROJECT_ENVIRONMENT",
            "REPLAY_TEST_ARTIFACT",
            "PYTEST_ADDOPTS",
        }
    }
    env["UV_PROJECT_ENVIRONMENT"] = str(checkout / ".venv")

    def stage(name, command, *, extra_env=None, timeout=600, junit=None):
        print(json.dumps({"stage": name, "status": "running"}), flush=True)
        try:
            process = subprocess.run(
                command,
                cwd=checkout,
                env={**env, **(extra_env or {})},
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            result = {
                "name": name,
                "exit_code": process.returncode,
                "passed": process.returncode == 0,
            }
            if junit and junit.exists():
                result["tests"] = test_summary(junit)
                result["passed"] &= (
                    bool(result["tests"]["total"])
                    and not result["tests"]["failed"]
                    and not result["tests"]["skipped"]
                )
            elif junit:
                result["passed"] = False
            report["stages"].append(result)
            save()
            print(json.dumps(result), flush=True)
            if not result["passed"]:
                raise RuntimeError("Acceptance stage failed; sanitized stage result preserved")
            return process.stdout
        except subprocess.TimeoutExpired:
            report["stages"].append({"name": name, "passed": False, "reason": "deadline_exceeded"})
            save()
            raise

    try:
        report["source_sha256"] = snapshot(ROOT, checkout)
        # Only inspect the requested repository's configured keys in memory.
        configured = [v for k, v in os.environ.items() if k.endswith("_API_KEY") and v]
        if (ROOT / ".env").exists():
            for line in (ROOT / ".env").read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    name, value = line.split("=", 1)
                    if name.strip().endswith("_API_KEY"):
                        configured.append(value.strip().strip("\"'"))
        for name in report["source_sha256"]:
            data = (checkout / name).read_bytes()
            if any(value.encode() in data for value in configured if len(value) > 8):
                raise ValueError("Configured secret detected in source; acceptance stopped")
        report["configured_secret_scan"] = "passed"
        # Retain a reproducible source archive before tests generate any cache files.
        shutil.make_archive(str(output / "source"), "gztar", root_dir=checkout)
        report["source_archive_sha256"] = digest(output / "source.tar.gz")
        report["uv_version"] = stage("uv_version", ["uv", "--version"]).strip()
        stage("locked_install", ["uv", "sync", "--locked"])
        python = str(checkout / ".venv/bin/python")
        report["python_version"] = stage("python_version", [python, "--version"]).strip()
        versions = stage(
            "installed_versions",
            [
                python,
                "-c",
                "import importlib.metadata,json; print(json.dumps({d.metadata['Name']:d.version for d in importlib.metadata.distributions()}))",
            ],
        )
        report["installed_versions"] = json.loads(versions)
        stage("matching_chromium", [python, "-m", "playwright", "install", "chromium"])
        stage("configuration", [str(checkout / ".venv/bin/computer-use"), "validate-config"])
        for label, paths, extra in [
            ("full_suite", ["tests"], {}),
            (
                "genuine_artifact_replay_and_handoff",
                ["tests/integration/test_replay.py", "tests/integration/test_handoff.py"],
                {"REPLAY_TEST_ARTIFACT": str(checkout / "evidence/phase7/capability.json")},
            ),
        ]:
            xml = workspace / (label + ".xml")
            stage(
                label,
                [python, "-m", "pytest", "-q", *paths, "--junitxml=" + str(xml)],
                extra_env=extra,
                junit=xml,
            )
        stage(
            "real_cli_scenarios",
            [python, "scripts/capture_acceptance.py", str(output / "scenarios")],
        )
        report["artifact_sha256"] = digest(checkout / "evidence/phase7/capability.json")
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(
            error
        ).__name__  # No command output or unsanitized exception text.
    finally:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        report["files_sha256"] = {
            str(p.relative_to(output)): digest(p)
            for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "acceptance.json"
        }
        save()
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "report": str(output / "acceptance.json"),
                    "temporary_workspace": str(workspace),
                }
            ),
            flush=True,
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

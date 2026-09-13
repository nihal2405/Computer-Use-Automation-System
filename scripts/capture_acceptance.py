"""Real CLI/browser runs against a separate synthetic server; no model calls.

Invoked inside the clean environment by acceptance.py. Hosting imports the mock
app only in this parent process. Replay children prohibit those imports.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Thread

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import request
from werkzeug.serving import make_server, WSGIRequestHandler
import yaml

from mock_app.app import create_app
from computer_use.capabilities.store import CapabilityStore
from computer_use.observability.events import Event
from computer_use.schemas.intervention import Intervention
from computer_use.schemas.result import result_adapter


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


def inspect_run(directory, result, member):
    """Validate existing evidence, including references and redaction, before export."""
    events = [Event.model_validate_json(line) for line in (directory / "events.jsonl").read_text().splitlines()]
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert all(e.run_id == result.run_id and e.session_id == result.session_id for e in events)
    assert not any(e.event.startswith("model_") for e in events)
    terminal = {"success": "run_completed", "business_outcome": "business_outcome", "failure": "run_failed"}
    assert events[-1].event == terminal[result.status]
    for event in events:
        if event.evidence_ref:
            assert (directory / (event.evidence_ref + ".json")).is_file()
    for path in directory.glob("*.json"):
        data = json.loads(path.read_text())
        if "resolution" in data:
            record = Intervention.model_validate(data)
            assert record.run_id == result.run_id and record.session_id == result.session_id
    text = "\n".join(p.read_text() for p in directory.iterdir())
    assert all(value not in text for value in ('"' + member + '"', "1250.75", "8040.20", "Avery Morgan", "Jordan Ellis"))
    # Every leaf in a structural snapshot is metadata, never UI text or values.
    snapshots = []
    def check_node(node):
        assert set(node) <= {"tag", "role", "visible", "disabled", "children"}
        for child in node.get("children", []):
            check_node(child)
    for path in directory.glob("*.json"):
        data = json.loads(path.read_text())
        if data.get("kind") == "dom_structure":
            for node in data["details"]["nodes"]:
                check_node(node)
            snapshots.append(path.name)
    if result.status == "failure":
        assert snapshots, "Failure must retain richer structural evidence"
        assert not any(e.event == "completed" and e.action == "read" for e in events)
    return events, snapshots


def main():
    root = Path(__file__).resolve().parents[1]
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifact = root / "evidence/phase7/capability.json"
    capability = CapabilityStore.load(artifact)
    assert capability.provenance == "llm_discovery"
    env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY")}
    cases = [
        ("success", "normal", "2002", "success", None, 1500),
        ("not_found", "normal", "9999", "business_outcome", "member_not_found", 1500),
        ("permission_denied", "permission_denied", "2002", "failure", "permission_denied", 1500),
        ("application_error", "application_error", "2002", "failure", "application_error", 1500),
        ("session_expired", "session_expired", "2002", "failure", "session_expired", 1500),
        ("invalid_input", "invalid_input", "2002", "failure", "invalid_input", 1500),
        ("recovered_loading", "slow_loading", "2002", "success", None, 1500),
        ("recovery_exhausted", "slow_loading", "2002", "failure", "recovery_exhausted", 60000),
    ]
    summaries = []
    for label, scenario, member, expected_status, expected_code, delay in cases:
        case = output / label
        case.mkdir()
        # Configuration belongs to the trusted runner; application state is only
        # obtained by the child via browser actions and reads.
        project = root / ".acceptance-projects" / label
        shutil.copytree(root / "config", project / "config")
        app = create_app({"DEFAULT_SCENARIO": scenario, "SLOW_LOAD_MS": delay})
        counts = {"search_posts": 0, "account_gets": 0, "other_requests": 0}
        @app.before_request
        def count_requests():
            if request.method == "POST" and request.path == "/members":
                counts["search_posts"] += 1
            elif request.method == "GET" and request.path.endswith("/accounts"):
                counts["account_gets"] += 1
            elif request.path not in {"/", "/members", f"/members/{member}"} and not request.path.startswith("/static/"):
                counts["other_requests"] += 1
        server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"
        for name, key, value in [("targets/mock_bank.yaml", "entry_url", origin + "/"),
                                 ("policy.yaml", "allowed_origins", [origin])]:
            path = project / "config" / name
            data = yaml.safe_load(path.read_text())
            data[key] = value
            path.write_text(yaml.safe_dump(data))
        try:
            cmd = [sys.executable, "scripts/replay_without_model.py", str(artifact), "--project", str(project),
                   "--inputs", json.dumps({"member_id": member}), "--headless"]
            child = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=150)
            envelope = json.loads(child.stdout)
            result = result_adapter.validate_python(envelope["result"])
            run_dir = project / "runs" / result.run_id
            events, snapshots = inspect_run(run_dir, result, member)
            # Copy actual sanitized diagnostics even if an expected outcome differs.
            shutil.copytree(run_dir, case / "run")
            summary = {"scenario": scenario, "run_id": result.run_id, "session_id": result.session_id,
                       "status": result.status, "code": getattr(result, "code", None), "exit_code": child.returncode,
                       "expected_status": expected_status, "expected_code": expected_code,
                       "model_imports_blocked": True, "mock_app_imports_blocked": True,
                       "api_keys_removed": True, "events": len(events), "snapshots": snapshots,
                       "request_counts": counts.copy(), "checkpoint_verified": getattr(result, "checkpoint_verified", False),
                       "configuration_overrides": {"origin": origin, "headless": True, "slow_load_ms": delay}}
            summary["passed"] = (result.status == expected_status and getattr(result, "code", None) == expected_code
                and child.returncode == {"success": 0, "business_outcome": 2, "failure": 1}[expected_status]
                and counts["search_posts"] == 1)
            if result.status == "success":
                summary["passed"] &= result.outputs == {"balance": "8040.20", "currency": "USD"}
            if label in {"recovered_loading", "recovery_exhausted"}:
                summary["passed"] &= any(e.event == "recovery_started" for e in events)
            (case / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            summaries.append(summary)
            print(json.dumps({"case": label, "status": result.status, "passed": summary["passed"]}), flush=True)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    return 0 if all(s["passed"] for s in summaries) else 1


if __name__ == "__main__":
    sys.exit(main())

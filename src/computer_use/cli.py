"""Commands for discovery, replay, configuration checks, and artifact validation."""

import argparse
import asyncio
import json
from pathlib import Path

from pydantic import ValidationError

from computer_use import __version__
from computer_use.schemas import TargetIdentity
from computer_use.settings import ConfigurationError, load_configuration


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover, validate, and replay browser workflows")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Show implementation status")
    config = commands.add_parser(
        "validate-config", help="Validate trusted runtime, target, and policy YAML"
    )
    config.add_argument("--project", type=Path, default=Path.cwd())
    replay = commands.add_parser(
        "replay", help="Replay a capability through the UI without a model"
    )
    replay.add_argument("path", type=Path)
    replay.add_argument("--inputs", required=True, help="Invocation inputs as a JSON object")
    replay.add_argument("--project", type=Path, default=Path.cwd())
    replay.add_argument(
        "--headless", action="store_true", help="Run without a visible browser window"
    )
    discover = commands.add_parser(
        "discover", help="Discover and compile a workflow using a real model"
    )
    discover.add_argument(
        "--task", type=Path, default=Path("config/tasks/read_savings_balance.json")
    )
    discover.add_argument("--inputs", required=True, help="Invocation inputs as JSON")
    discover.add_argument("--project", type=Path, default=Path.cwd())
    discover.add_argument(
        "--goal", help="Goal text; outputs, target and checkpoint remain task-defined"
    )
    discover.add_argument("--headless", action="store_true")
    for command in (replay, discover):
        command.add_argument(
            "--interactive",
            action="store_true",
            help="Keep a blocked browser alive for local operator takeover",
        )
        command.add_argument(
            "--operator-timeout",
            type=int,
            default=900,
            help="Maximum operator wait in seconds (1–3600)",
        )
    validate = commands.add_parser(
        "validate-capability", help="Validate a capability without executing it"
    )
    validate.add_argument("path", type=Path)
    validate.add_argument("--inputs", help="Optional invocation inputs as a JSON object")
    validate.add_argument("--target", type=Path, help="Optional target identity JSON file")
    args = parser.parse_args()
    if getattr(args, "interactive", False) and args.headless:
        parser.error("Interactive takeover requires a visible browser; omit --headless")
    if hasattr(args, "operator_timeout") and not 1 <= args.operator_timeout <= 3600:
        parser.error("Operator timeout must be between 1 and 3600 seconds")
    if args.command == "discover":
        from playwright.async_api import Error as BrowserError

        from computer_use.discovery.agent import DiscoveryAgent
        from computer_use.discovery.model_client import ModelError, OpenAIModel
        from computer_use.observability.evidence import PersistenceError
        from computer_use.settings import Configuration
        from computer_use.surfaces.base import SurfaceError

        async def discover_run():
            model = OpenAIModel.from_project(args.project)
            try:
                configuration = load_configuration(args.project)
                if args.headless or args.interactive:
                    data = configuration.model_dump()
                    data["runtime"]["browser"]["headless"] = args.headless
                    configuration = Configuration.model_validate(data)
                task_path = args.task if args.task.is_absolute() else args.project / args.task
                agent = DiscoveryAgent.from_project(
                    args.project,
                    task_path=task_path,
                    inputs=json.loads(args.inputs),
                    model=model,
                    configuration=configuration,
                    goal=args.goal,
                )
                if args.interactive:
                    from computer_use.handoff.operator import run_interactive

                    result = await run_interactive(agent, wait_timeout=args.operator_timeout)
                else:
                    async with agent:
                        result = await agent.run()
                return agent, result
            finally:
                await model.close()

        try:
            agent, result = asyncio.run(discover_run())
            print(
                json.dumps(
                    {
                        "result": result.model_dump(mode="json"),
                        "artifact": str(agent.artifact_path) if agent.artifact_path else None,
                        "provenance": agent.capability.provenance if agent.capability else None,
                        "model_responses": len(agent.recorder.model_responses),
                        "provider_failure": agent.provider_failure,
                        "human_assisted": agent.human_assisted,
                        "session_retained": False,
                    },
                    indent=2,
                )
            )
            return {"success": 0, "business_outcome": 2, "failure": 1}[result.status]
        except (ModelError, SurfaceError) as error:
            print(json.dumps({"status": "failure", "code": error.code}))
        except (PersistenceError, BrowserError, OSError, ValueError, TypeError):
            print(json.dumps({"status": "failure", "code": "discovery_setup_or_runtime_failed"}))
        return 1
    if args.command == "replay":
        from playwright.async_api import Error as BrowserError

        from computer_use.capabilities.store import ArtifactError, CapabilityStore
        from computer_use.observability.evidence import PersistenceError
        from computer_use.replay.engine import ReplayEngine, ReplayRequestError
        from computer_use.settings import Configuration

        try:
            configuration = load_configuration(args.project)
            if args.headless or args.interactive:
                data = configuration.model_dump()
                data["runtime"]["browser"]["headless"] = args.headless
                configuration = Configuration.model_validate(data)
            capability = CapabilityStore.load(args.path)
            engine = ReplayEngine(
                capability=capability,
                configuration=configuration,
                project_root=args.project,
                inputs=json.loads(args.inputs),
            )
        except (
            ArtifactError,
            ReplayRequestError,
            ConfigurationError,
            ValueError,
            TypeError,
        ) as error:
            print(
                json.dumps(
                    {
                        "status": "failure",
                        "code": getattr(error, "code", "invalid_input"),
                        "executed": False,
                    }
                )
            )
            return 1
        try:

            async def run():
                if args.interactive:
                    from computer_use.handoff.operator import run_interactive

                    return await run_interactive(engine, wait_timeout=args.operator_timeout)
                async with engine:
                    return await engine.run()

            result = asyncio.run(run())
            print(
                json.dumps(
                    {
                        "provenance": capability.provenance,
                        "model_used": False,
                        "session_retained": False,
                        "result": result.model_dump(mode="json"),
                    },
                    indent=2,
                )
            )
            return {"success": 0, "business_outcome": 2, "failure": 1}[result.status]
        except (PersistenceError, BrowserError, OSError, ValueError, TypeError):
            print(
                json.dumps(
                    {
                        "status": "failure",
                        "code": "replay_runtime_or_setup_failed",
                        "model_used": False,
                    }
                )
            )
            return 1
    if args.command == "validate-config":
        try:
            configuration = load_configuration(args.project)
        except ConfigurationError:
            print(json.dumps({"status": "invalid", "code": "invalid_configuration"}))
            return 2
        print(
            json.dumps(
                {
                    "status": "valid",
                    "policy_rules": len(configuration.policy.rules),
                    "executed": False,
                }
            )
        )
        return 0
    if args.command == "validate-capability":
        from computer_use.capabilities.store import CapabilityStore

        try:
            capability = CapabilityStore.load(args.path)
            if args.inputs is not None:
                capability.validate_inputs(json.loads(args.inputs))
            if args.target is not None:
                capability.validate_target(
                    TargetIdentity.model_validate_json(args.target.read_text(encoding="utf-8"))
                )
        except (ValueError, OSError) as error:
            # Model errors can contain raw inputs. Print only a bounded, generic summary.
            result = {"status": "invalid", "code": "invalid_contract_or_invocation"}
            if isinstance(error, ValidationError):
                result["error_count"] = error.error_count()
            print(json.dumps(result))
            return 2
        print(
            json.dumps(
                {
                    "status": "valid",
                    "capability_id": capability.id,
                    "provenance": capability.provenance,
                    "steps": len(capability.steps),
                    "inputs_checked": args.inputs is not None,
                    "target_checked": args.target is not None,
                    "executed": False,
                },
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            {
                "project": "computer-use-automation",
                "version": __version__,
                "status": "discovery_replay_ready",
                "shared_executor_implemented": True,
                "policy_enforced": True,
                "redacted_persistence_implemented": True,
                "browser_adapter_implemented": True,
                "session_ownership_implemented": True,
                "mock_app_implemented": True,
                "contracts_implemented": True,
                "discovery_implemented": True,
                "replay_implemented": True,
                "handoff_implemented": True,
                "evidence_collected": True,
                "handoff_evidence_collected": True,
            },
            indent=2,
        )
    )
    return 0

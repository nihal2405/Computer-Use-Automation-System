"""Local manual acceptance demo; starts a private synthetic bank with its dialog enabled."""

import asyncio
import sys
from pathlib import Path
from threading import Thread

# The mock server is repository source, deliberately not part of the automation
# package. Make it importable when this script is launched by its documented path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from werkzeug.serving import WSGIRequestHandler, make_server

from computer_use.capabilities.store import CapabilityStore
from computer_use.handoff.operator import run_interactive
from computer_use.replay.engine import ReplayEngine
from computer_use.settings import Configuration, load_configuration
from mock_app.app import create_app


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


async def main():
    root = Path(__file__).resolve().parents[1]
    # Hosting is setup only. Replay obtains all output through Chromium, not app data.
    server = make_server(
        "127.0.0.1",
        0,
        create_app({"DEFAULT_SCENARIO": "unexpected_dialog"}),
        threaded=True,
        request_handler=QuietHandler,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    config = load_configuration(root).model_dump()
    config["target"]["entry_url"] = origin + "/"
    config["policy"]["allowed_origins"] = [origin]
    config["runtime"]["browser"]["headless"] = False
    engine = ReplayEngine(
        capability=CapabilityStore.load(root / "evidence/phase7/capability.json"),
        configuration=Configuration.model_validate(config),
        project_root=root,
        inputs={"member_id": "2002"},
    )
    try:
        result = await run_interactive(engine)
        print(result.model_dump_json(indent=2), flush=True)
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        await asyncio.to_thread(thread.join, 5)


if __name__ == "__main__":
    asyncio.run(main())

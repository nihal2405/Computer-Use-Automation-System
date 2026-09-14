"""Shared synthetic bank fixture for replay, discovery, and handoff tests."""

from threading import Thread

import pytest
from flask import request
from werkzeug.serving import make_server

from mock_app.app import create_app


@pytest.fixture
def bank():
    state = {"scenario": "normal", "requests": [], "replace": None, "delay": 1500}
    app = create_app({"TESTING": True})

    @app.before_request
    def record():
        app.config.update(DEFAULT_SCENARIO=state["scenario"], SLOW_LOAD_MS=state["delay"])
        state["requests"].append((request.method, request.path))

    # Configure the scenario before the app initializes this browser's session.
    app.before_request_funcs[None].insert(0, app.before_request_funcs[None].pop())

    @app.after_request
    def change_page(response):
        if state["replace"] and request.path.endswith("/accounts"):
            old, new = state["replace"]
            response.set_data(response.get_data(as_text=True).replace(old, new))
        return response

    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()

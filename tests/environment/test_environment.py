"""Verify the installed development stack; this is not a banking workflow test."""

from threading import Thread

import pytest
import yaml
from flask import Flask, render_template_string
from playwright.sync_api import expect, sync_playwright
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from werkzeug.serving import make_server


class SmokeSettings(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    title: str
    timeout_ms: int = Field(gt=0)


@pytest.fixture
def local_page():
    """Serve a disposable page on loopback using an OS-assigned port."""
    settings = SmokeSettings.model_validate(
        yaml.safe_load("title: Environment ready\ntimeout_ms: 5000\n")
    )
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(
            """<!doctype html>
            <html lang="en">
              <head><title>{{ title }}</title></head>
              <body>
                <h1>{{ title }}</h1>
                <button onclick="document.querySelector('[role=status]').textContent='Clicked'">
                  Check browser
                </button>
                <p role="status">Waiting</p>
              </body>
            </html>""",
            title=settings.title,
        )

    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", settings
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_chromium_can_operate_local_flask_page(local_page):
    """Exercise YAML, validation, templating, HTTP, browser launch, and clicking."""
    url, settings = local_page
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_default_timeout(settings.timeout_ms)
            response = page.goto(url)
            assert response is not None and response.status == 200
            expect(page.get_by_role("heading", name=settings.title)).to_be_visible()
            page.get_by_role("button", name="Check browser").click()
            expect(page.get_by_role("status")).to_have_text("Clicked")
        finally:
            browser.close()


def test_configuration_validation_rejects_invalid_types():
    with pytest.raises(ValidationError):
        SmokeSettings.model_validate(
            yaml.safe_load("title: Environment ready\ntimeout_ms: invalid\n")
        )

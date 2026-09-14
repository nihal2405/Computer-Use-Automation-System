"""Browser checks for the mock app, independent of automation controllers."""

from threading import Thread

import pytest
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from mock_app.app import create_app


@pytest.fixture(scope="module")
def bank_url():
    app = create_app({"TESTING": True, "SLOW_LOAD_MS": 1200})
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(browser, bank_url):
    context = browser.new_context(viewport={"width": 1365, "height": 900})
    page = context.new_page()
    page.set_default_timeout(5000)
    page.goto(bank_url)
    yield page
    context.close()


def select_scenario(page, value):
    page.get_by_role("link", name="Demo controls", exact=True).click()
    page.get_by_label("Scenario", exact=True).select_option(value)
    page.get_by_role("button", name="Apply scenario", exact=True).click()
    expect(page.get_by_role("heading", name="Member search", exact=True)).to_be_visible()


def search(page, member_id):
    page.get_by_label("Member ID", exact=True).fill(member_id)
    page.get_by_role("button", name="Search", exact=True).click()


def open_accounts(page, member_id="1001"):
    search(page, member_id)
    page.get_by_role("link", name=member_id, exact=True).click()
    expect(page.get_by_role("heading", name="Member details", exact=True)).to_be_visible()
    page.get_by_role("link", name="Accounts", exact=True).click()


@pytest.mark.parametrize(("member_id", "balance"), [("1001", "1250.75"), ("2002", "8040.20")])
def test_person_can_retrieve_each_members_savings(page, member_id, balance):
    open_accounts(page, member_id)
    expect(page.get_by_role("heading", name="Accounts", exact=True)).to_be_visible()
    expect(page.locator(".accounts-member-id")).to_have_text(member_id)
    expect(page.locator("td.savings-balance")).to_have_count(1)
    expect(page.locator("td.savings-balance")).to_have_text(balance)
    expect(page.locator("td.savings-currency")).to_have_text("USD")
    expect(page.get_by_role("rowheader", name="Checking")).to_be_visible()


@pytest.mark.parametrize("member_id", ["", "abc", "12", "１２３４"])
def test_invalid_input_is_visible_in_browser(page, member_id):
    search(page, member_id)
    expect(page.get_by_role("alert")).to_contain_text("Invalid member ID")
    expect(page.get_by_label("Member ID", exact=True)).to_have_attribute("aria-invalid", "true")


@pytest.mark.parametrize(
    ("scenario", "member_id"), [("normal", "9999"), ("missing_member", "1001")]
)
def test_browser_not_found_scenarios(page, scenario, member_id):
    select_scenario(page, scenario)
    search(page, member_id)
    expect(page.get_by_role("heading", name="No matching member", exact=True)).to_be_visible()
    expect(page.locator("body")).to_have_attribute("data-state", "member_not_found")


def test_forced_invalid_input_scenario(page):
    select_scenario(page, "invalid_input")
    search(page, "1001")
    expect(page.get_by_role("alert")).to_contain_text("rejects all searches")


def test_loading_is_visible_then_results_appear(page):
    select_scenario(page, "slow_loading")
    search(page, "1001")
    expect(page.get_by_role("status")).to_have_text("Loading")
    expect(page.get_by_role("link", name="1001", exact=True)).to_have_count(0)
    expect(page.get_by_role("link", name="1001", exact=True)).to_be_visible()
    page.get_by_role("link", name="1001", exact=True).click()
    page.get_by_role("link", name="Accounts", exact=True).click()
    expect(page.locator("td.savings-balance")).to_have_text("1250.75")


@pytest.mark.parametrize(
    ("scenario", "title", "status"),
    [
        ("permission_denied", "Permission denied", 403),
        ("application_error", "Application unavailable", 503),
    ],
)
def test_account_failures_render_without_balances(page, scenario, title, status):
    select_scenario(page, scenario)
    search(page, "1001")
    page.get_by_role("link", name="1001", exact=True).click()
    with page.expect_response(
        lambda response: response.url.endswith("/members/1001/accounts")
    ) as response:
        page.get_by_role("link", name="Accounts", exact=True).click()
    assert response.value.status == status
    expect(page.get_by_role("heading", name=title, exact=True).first).to_be_visible()
    expect(page.locator("td.savings-balance")).to_have_count(0)
    assert "1250.75" not in page.content()


def test_session_expiry_can_be_resolved_in_the_same_browser(page):
    select_scenario(page, "session_expired")
    open_accounts(page)
    expect(page.get_by_role("heading", name="Session expired", exact=True).first).to_be_visible()
    expect(page.locator("td.savings-balance")).to_have_count(0)
    page.get_by_role("button", name="Restart demo session", exact=True).click()
    open_accounts(page)
    expect(page.locator("td.savings-balance")).to_have_text("1250.75")


def test_dialog_is_blocking_and_a_person_can_acknowledge_it(page):
    select_scenario(page, "unexpected_dialog")
    open_accounts(page)
    expect(page.get_by_role("dialog", name="Additional review required")).to_be_visible()
    assert page.locator("dialog").evaluate("node => node.matches(':modal')")
    expect(page.locator("td.savings-balance")).to_have_count(0)
    assert "1250.75" not in page.content()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_be_visible()
    page.get_by_role("button", name="Continue to accounts", exact=True).click()
    expect(page.locator("td.savings-balance")).to_have_text("1250.75")
    page.reload()
    expect(page.get_by_role("dialog")).to_have_count(0)
    select_scenario(page, "unexpected_dialog")
    open_accounts(page)
    expect(page.get_by_role("dialog")).to_be_visible()


def test_normal_scenario_restores_workflow(page):
    select_scenario(page, "permission_denied")
    open_accounts(page)
    select_scenario(page, "normal")
    open_accounts(page, "2002")
    expect(page.locator("td.savings-balance")).to_have_text("8040.20")


def test_mobile_search_and_accounts_remain_usable(page):
    page.set_viewport_size({"width": 390, "height": 844})
    open_accounts(page, "2002")
    expect(page.locator("td.savings-balance")).to_have_text("8040.20")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

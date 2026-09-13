"""Target application checks; these do not implement the automation runtime."""

import re

import pytest

from mock_app.app import create_app


@pytest.fixture
def app():
    return create_app({"TESTING": True, "SLOW_LOAD_MS": 1800})


@pytest.fixture
def client(app):
    return app.test_client()


def post_form(client, path, data, page="/"):
    response = client.get(page)
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
    assert token, "Expected a form token on the UI page"
    return client.post(path, data={**data, "csrf_token": token.group(1)}, follow_redirects=True)


def choose_scenario(client, scenario):
    return post_form(client, "/demo", {"scenario": scenario}, page="/demo")


@pytest.mark.parametrize(("member_id", "name", "balance"), [
    ("1001", "Avery Morgan", "1250.75"), ("2002", "Jordan Ellis", "8040.20"),
])
def test_entire_html_workflow(client, member_id, name, balance):
    result = post_form(client, "/members", {"member_id": member_id})
    assert result.status_code == 200
    assert f'href="/members/{member_id}"' in result.text
    assert name in result.text
    assert balance not in result.text
    detail = client.get(f"/members/{member_id}")
    assert detail.status_code == 200 and name in detail.text
    assert balance not in detail.text
    accounts = client.get(f"/members/{member_id}/accounts")
    assert accounts.status_code == 200 and accounts.mimetype == "text/html"
    assert balance in accounts.text and "USD" in accounts.text
    assert f'class="accounts-member-id">{member_id}</strong>' in accounts.text
    assert "Checking" in accounts.text and "Savings" in accounts.text


@pytest.mark.parametrize("member_id", ["", "123", "abc", "10000000000", "１２３４", "<script>alert(1)</script>"])
def test_invalid_search_is_explicit_and_escaped(client, member_id):
    response = post_form(client, "/members", {"member_id": member_id})
    assert response.status_code == 400
    assert 'data-state="validation_error"' in response.text
    assert 'role="alert"' in response.text
    assert '<script>alert(1)</script>' not in response.text
    with client.session_transaction() as state:
        assert "last_search" not in state


def test_search_normalizes_whitespace_without_converting_ids_to_numbers(client):
    assert "Avery Morgan" in post_form(client, "/members", {"member_id": " 1001 "}).text
    response = post_form(client, "/members", {"member_id": "01001"})
    assert "No matching member" in response.text
    assert "01001" in response.text


@pytest.mark.parametrize(("scenario", "member_id"), [("normal", "9999"), ("missing_member", "1001")])
def test_not_found_is_a_successful_search_outcome(client, scenario, member_id):
    choose_scenario(client, scenario)
    response = post_form(client, "/members", {"member_id": member_id})
    assert response.status_code == 200
    assert 'data-state="member_not_found"' in response.text
    assert "No matching member" in response.text
    assert "Avery Morgan" not in response.text


def test_invalid_input_scenario_rejects_valid_id(client):
    choose_scenario(client, "invalid_input")
    response = post_form(client, "/members", {"member_id": "1001"})
    assert response.status_code == 400
    assert "This demo scenario rejects all searches" in response.text


def test_slow_loading_withholds_results_until_deadline(client, monkeypatch):
    now = [100.0]
    monkeypatch.setattr("mock_app.app.monotonic", lambda: now[0])
    choose_scenario(client, "slow_loading")
    response = post_form(client, "/members", {"member_id": "1001"})
    assert response.status_code == 200
    assert 'data-state="loading"' in response.text
    assert "Avery Morgan" not in response.text
    assert 'href="/members/1001"' not in response.text
    now[0] += 2
    response = client.get("/members")
    assert 'data-state="ready"' in response.text
    assert 'href="/members/1001"' in response.text


@pytest.mark.parametrize(("scenario", "status", "title"), [
    ("permission_denied", 403, "Permission denied"),
    ("session_expired", 401, "Session expired"),
    ("application_error", 503, "Application unavailable"),
    ("unexpected_dialog", 200, "Additional review required"),
])
def test_blocked_accounts_never_embed_balances(client, scenario, status, title):
    choose_scenario(client, scenario)
    response = client.get("/members/1001/accounts")
    assert response.status_code == status
    assert title in response.text
    assert "1250.75" not in response.text
    assert "342.18" not in response.text
    assert "td.savings-balance" not in response.text


def test_dialog_acknowledgement_preserves_session_and_is_member_specific(client):
    choose_scenario(client, "unexpected_dialog")
    with client.session_transaction() as state:
        original_session_id = state["demo_session_id"]
    response = post_form(client, "/members/1001/accounts", {"decision": "acknowledge"}, page="/members/1001/accounts")
    assert response.status_code == 200 and "1250.75" in response.text
    assert "Additional review required" in client.get("/members/2002/accounts").text
    with client.session_transaction() as state:
        assert state["demo_session_id"] == original_session_id
    choose_scenario(client, "unexpected_dialog")
    assert "Additional review required" in client.get("/members/1001/accounts").text


def test_expiry_is_repeatable_and_restart_is_explicit(client):
    choose_scenario(client, "session_expired")
    assert client.get("/members/1001/accounts").status_code == 401
    assert client.get("/members/1001/accounts").status_code == 401
    response = post_form(client, "/session/restart", {}, page="/members/1001/accounts")
    assert response.status_code == 200 and "Member search" in response.text
    assert "1250.75" in client.get("/members/1001/accounts").text
    choose_scenario(client, "session_expired")
    assert client.get("/members/1001/accounts").status_code == 401


def test_scenarios_are_isolated_between_browser_sessions(app):
    first, second = app.test_client(), app.test_client()
    choose_scenario(first, "permission_denied")
    assert first.get("/members/1001/accounts").status_code == 403
    assert second.get("/members/1001/accounts").status_code == 200


def test_normal_scenario_resets_previous_workflow_state(client):
    choose_scenario(client, "unexpected_dialog")
    post_form(client, "/members", {"member_id": "1001"})
    post_form(client, "/members/1001/accounts", {"decision": "acknowledge"}, page="/members/1001/accounts")
    choose_scenario(client, "normal")
    with client.session_transaction() as state:
        assert "last_search" not in state and "acknowledged_member" not in state
    assert client.get("/members/1001/accounts").status_code == 200


def test_unknown_scenario_does_not_change_current_selection(client):
    choose_scenario(client, "slow_loading")
    assert choose_scenario(client, "unknown").status_code == 400
    with client.session_transaction() as state:
        assert state["scenario"] == "slow_loading"


@pytest.mark.parametrize("token", ["", "invalid", "☃"])
def test_forms_reject_missing_or_invalid_csrf(client, token):
    client.get("/")
    assert client.post("/demo", data={"scenario": "permission_denied", "csrf_token": token}).status_code == 400
    with client.session_transaction() as state:
        assert state["scenario"] == "normal"


@pytest.mark.parametrize("path", ["/api/members", "/api/balance", "/members/9999", "/members/9999/accounts"])
def test_unknown_pages_have_no_data_endpoint_or_traceback(client, path):
    response = client.get(path)
    assert response.status_code == 404 and response.mimetype == "text/html"
    assert "Traceback" not in response.text


def test_stale_or_unavailable_operator_actions_are_rejected(client):
    assert post_form(client, "/session/restart", {}).status_code == 400
    assert post_form(client, "/members/1001/accounts", {"decision": "acknowledge"}).status_code == 400


def test_page_and_assets_are_self_contained(client):
    response = client.get("/")
    assert 'data-product="synthetic_bank" data-version="1.0"' in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    for path in ("/static/styles.css", "/static/app.js"):
        assert client.get(path).status_code == 200

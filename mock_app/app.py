"""Server-rendered synthetic bank UI with session-scoped failure scenarios."""

import hmac
import re
import secrets
from time import monotonic

from flask import Flask, abort, redirect, render_template, request, session, url_for

from mock_app.data import MEMBERS
from mock_app.scenarios import SCENARIOS


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=secrets.token_hex(32),
        SESSION_COOKIE_NAME="synthetic_bank_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=16_384,
        SLOW_LOAD_MS=1800,
    )
    if test_config:
        app.config.update(test_config)
    app.config.setdefault("DEFAULT_SCENARIO", "normal")
    if app.config["DEFAULT_SCENARIO"] not in SCENARIOS:
        raise ValueError("Unknown default demo scenario")

    @app.before_request
    def initialize_session_and_check_form():
        if request.endpoint == "static":
            return None
        session.setdefault("demo_session_id", secrets.token_hex(12))
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        session.setdefault("scenario", app.config["DEFAULT_SCENARIO"])
        if request.method == "POST":
            submitted = request.form.get("csrf_token", "")
            if not hmac.compare_digest(submitted.encode(), session["csrf_token"].encode()):
                abort(400, description="This form expired. Reload the page and try again.")
        return None

    @app.context_processor
    def shared_context():
        return {
            "scenario": SCENARIOS[session.get("scenario", "normal")],
            "csrf_token": session.get("csrf_token", ""),
            "product_version": "1.0",
        }

    @app.after_request
    def response_headers(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
        )
        return response

    def get_member(member_id: str):
        member = MEMBERS.get(member_id)
        if member is None:
            abort(404)
        return member

    def account_error(title: str, message: str, status: int, state: str, member):
        return render_template(
            "error.html", title=title, message=message, status=status, state=state, member=member,
        ), status

    @app.get("/")
    def search():
        return render_template("search.html", title="Member search", state="ready", member_id="")

    @app.route("/members", methods=["GET", "POST"])
    def members():
        if request.method == "POST":
            member_id = request.form.get("member_id", "").strip()
            # A new search always clears any previous result and acknowledgement.
            for key in ("last_search", "results_ready_at", "acknowledged_member"):
                session.pop(key, None)
            if not re.fullmatch(r"[0-9]{4,10}", member_id) or session["scenario"] == "invalid_input":
                message = "Enter a member ID containing 4 to 10 digits."
                if session["scenario"] == "invalid_input":
                    message = "This demo scenario rejects all searches. Choose Normal workflow to continue."
                return render_template(
                    "search.html", title="Member search", state="validation_error",
                    member_id=member_id[:100], validation_message=message,
                ), 400
            session["last_search"] = member_id
            if session["scenario"] == "slow_loading":
                session["results_ready_at"] = monotonic() + app.config["SLOW_LOAD_MS"] / 1000
            return redirect(url_for("members"), code=303)

        member_id = session.get("last_search")
        if member_id is None:
            return redirect(url_for("search"))
        remaining_ms = int((session.get("results_ready_at", 0) - monotonic()) * 1000)
        if session["scenario"] == "slow_loading" and remaining_ms > 0:
            return render_template(
                "loading.html", title="Searching members", state="loading",
                retry_ms=min(max(remaining_ms + 50, 100), 2000),
            )
        member = None if session["scenario"] == "missing_member" else MEMBERS.get(member_id)
        return render_template(
            "results.html", title="Search results", state="ready" if member else "member_not_found",
            member=member, member_id=member_id,
        )

    @app.get("/members/<member_id>")
    def member_detail(member_id: str):
        return render_template(
            "member.html", title="Member details", state="ready", member=get_member(member_id),
        )

    @app.route("/members/<member_id>/accounts", methods=["GET", "POST"])
    def accounts(member_id: str):
        member = get_member(member_id)
        active = session["scenario"]
        if request.method == "POST":
            if active != "unexpected_dialog" or request.form.get("decision") != "acknowledge":
                abort(400, description="This acknowledgement is not available.")
            session["acknowledged_member"] = member_id
            return redirect(url_for("accounts", member_id=member_id), code=303)
        if active == "permission_denied":
            return account_error(
                "Permission denied", "Your demo role does not have access to this member's accounts. "
                "Choose Normal workflow in Demo controls to restore access.", 403, "permission_denied", member,
            )
        if active == "session_expired" and not session.get("session_restarted"):
            session["expired"] = True
            return account_error(
                "Session expired", "The demo session has expired. Restart it, then search for the member again.",
                401, "session_expired", member,
            )
        if active == "application_error":
            return account_error(
                "Application unavailable", "Account services are temporarily unavailable in this scenario. "
                "Choose Normal workflow in Demo controls to restore the service.", 503, "application_error", member,
            )
        if active == "unexpected_dialog" and session.get("acknowledged_member") != member_id:
            return render_template(
                "dialog.html", title="Review required", state="unexpected_dialog", member=member,
            )
        return render_template("accounts.html", title="Accounts", state="ready", member=member)

    @app.route("/demo", methods=["GET", "POST"])
    def demo_controls():
        if request.method == "POST":
            selected = request.form.get("scenario")
            if selected not in SCENARIOS:
                abort(400, description="Choose a scenario from the list.")
            # Retain session identity; clear workflow state so every scenario is repeatable.
            for key in ("last_search", "results_ready_at", "acknowledged_member", "expired", "session_restarted"):
                session.pop(key, None)
            session["scenario"] = selected
            return redirect(url_for("search"), code=303)
        return render_template(
            "demo.html", title="Demo controls", state="ready", scenarios=SCENARIOS.values(),
        )

    @app.post("/session/restart")
    def restart_session():
        if session["scenario"] != "session_expired" or not session.get("expired"):
            abort(400, description="There is no expired demo session to restart.")
        session["session_restarted"] = True
        session.pop("expired", None)
        session.pop("last_search", None)
        return redirect(url_for("search"), code=303)

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("error.html", title="Request could not be completed",
                               message=error.description, status=400, state="validation_error"), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", title="Page not found",
                               message="This page or synthetic member does not exist.", status=404, state="unknown"), 404

    return app

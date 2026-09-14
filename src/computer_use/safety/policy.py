"""Trusted action rules and a context-wide, default-deny browser request boundary."""

import re
from urllib.parse import parse_qs, urljoin

from playwright.async_api import Error as DriverError

from computer_use.execution.targeting import bind_references
from computer_use.safety.urls import split_url
from computer_use.settings import PolicySettings
from computer_use.surfaces.base import SurfaceError


def denied():
    return SurfaceError(
        "policy_denied",
        "An explicitly approved operation and destination",
        "Policy blocked this operation",
    )


def canonical(value):
    if isinstance(value, dict):
        return {
            k: canonical(v)
            for k, v in value.items()
            if k not in {"rationale", "output", "timeout_ms"} and v is not None
        }
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


class Policy:
    def __init__(self, settings: PolicySettings):
        # Own a private copy: mutable lists in callers' frozen models cannot widen policy.
        self._settings = PolicySettings.model_validate_json(settings.model_dump_json())
        self._origins = frozenset(split_url(v)[0] for v in self._settings.allowed_origins)

    def inputs(self, values):
        if not isinstance(values, dict) or set(values) != set(self._settings.input_patterns):
            raise SurfaceError(
                "invalid_input", "Exactly the configured inputs", "Input names do not match"
            )
        for key, pattern in self._settings.input_patterns.items():
            if type(values[key]) is not str or re.fullmatch(pattern, values[key]) is None:
                raise SurfaceError(
                    "invalid_input",
                    "Inputs matching the configured types and patterns",
                    "Input validation failed",
                )
        return dict(values)

    def url(self, url, *, method="GET", resource=False):
        try:
            origin, path = split_url(url)
        except ValueError:
            raise denied() from None
        rules = self._settings.resources if resource else self._settings.navigation
        if origin not in self._origins or not any(
            method in r.methods and re.fullmatch(r.path, path) for r in rules
        ):
            raise denied()

    def authorize(self, action, operation, inputs, current_url, base_url):
        if current_url != "about:blank":
            self.url(current_url)
        elif action.action != "navigate":
            raise denied()
        actual = canonical(action.model_dump())
        for rule in self._settings.rules:
            if rule.operation != operation or rule.action != action.action:
                continue
            expected = canonical(bind_references(rule, inputs))
            expected.pop("operation")
            if action.action == "navigate":
                if re.fullmatch(rule.path, action.path):
                    self.url(base_url + action.path)
                    return
            elif actual == expected:
                return
        raise denied()

    def condition_operation(self, condition, inputs, *, action="verify"):
        """Select an existing reviewed rule; artifact conditions cannot grant access."""
        actual = canonical(bind_references(condition, inputs))
        for rule in self._settings.rules:
            if rule.action == action and rule.condition is not None:
                if canonical(bind_references(rule.condition, inputs)) == actual:
                    return rule.operation
        raise denied()

    def human_request(self, request, inputs):
        """Narrow banking acknowledgement permission, invoked only under human ownership."""
        origin, path = split_url(request.url)
        if (
            origin not in self._origins
            or path != f"/members/{inputs.get('member_id')}/accounts"
            or len(request.post_data or "") > 16_384
            or not request.headers.get("content-type", "").startswith(
                "application/x-www-form-urlencoded"
            )
        ):
            raise denied()
        fields = parse_qs(request.post_data or "", keep_blank_values=True, max_num_fields=10)
        for rule in self._settings.human_requests:
            if request.method == rule.method and re.fullmatch(rule.path, path):
                if (
                    set(fields) == set(rule.fields) | set(rule.ignored_fields)
                    and all(fields.get(k) == [v] for k, v in rule.fields.items())
                    and all(len(fields[k]) == 1 for k in rule.ignored_fields)
                ):
                    return
        raise denied()

    def control(self, action, metadata):
        """Check the actual resolved DOM control, not only a caller's operation label."""
        if action.action == "fill":
            if metadata["tag"] != "INPUT" or metadata["type"] not in {"text", "search"}:
                raise denied()
        if action.action == "click":
            if metadata["download"] or metadata["target"] not in {"", "_self"}:
                raise denied()
            if metadata["tag"] == "A":
                self.url(metadata["href"])
            elif (
                metadata["tag"] in {"BUTTON", "INPUT"}
                and metadata["type"] == "submit"
                and metadata["form_action"]
            ):
                self.url(metadata["form_action"], method=metadata["method"])
            else:
                # Arbitrary JavaScript-only controls require a reviewed adapter extension.
                raise denied()
            if re.search(
                r"\b(delete|remove|transfer|withdraw|pay|payment|purchase|send money)\b",
                metadata["text"],
                re.I,
            ):
                raise denied()

    def vocabulary(self):
        """Only operator-reviewed constants may survive text redaction verbatim."""

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for key, item in value.items():
                    if key != "rationale":
                        yield from strings(item)
            elif isinstance(value, list):
                for item in value:
                    yield from strings(item)

        return set(strings(self._settings.model_dump())) | set(self._settings.input_patterns)


class BrowserBoundary:
    def __init__(self, policy):
        self.policy = policy
        self.page = None
        self.operation = None
        self.submission = None
        self.blocked = False
        self._cdp = None
        self.human_authorizer = None

    async def attach(self, context, page):
        self.page = page
        self._cdp = await context.new_cdp_session(page)
        self._cdp.on("Fetch.requestPaused", self._response)
        # Playwright routing does not intercept every redirect hop. Pause responses
        # before Chromium follows Location; never proxy/reissue application requests.
        await self._cdp.send(
            "Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Response"}]}
        )

    async def _response(self, event):
        request_id = event["requestId"]
        try:
            request = event["request"]
            status = event.get("responseStatusCode", 0)
            headers = event.get("responseHeaders", [])
            if self.blocked or any(
                h["name"].lower() == "content-disposition" and "attachment" in h["value"].lower()
                for h in headers
            ):
                raise denied()
            if status in {301, 302, 303, 307, 308}:
                locations = [h["value"] for h in headers if h["name"].lower() == "location"]
                if len(locations) != 1:
                    raise denied()
                method = request["method"]
                if status == 303 or (status in {301, 302} and method == "POST"):
                    method = "GET"
                if method != "GET":  # Never repeat a submission via 307/308.
                    raise denied()
                self.policy.url(
                    urljoin(request["url"], locations[0]),
                    method=method,
                    resource=event.get("resourceType") != "Document",
                )
            await self._cdp.send("Fetch.continueRequest", {"requestId": request_id})
        except (SurfaceError, DriverError, ValueError, KeyError):
            self.blocked = True
            try:
                await self._cdp.send(
                    "Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"}
                )
            except DriverError:
                pass  # Context shutdown may have already cancelled the paused request.

    def check(self):
        if self.blocked:
            raise denied()

    async def route(self, route, request):
        try:
            if self.blocked or self.page is None or request.frame != self.page.main_frame:
                raise denied()
            navigation = request.is_navigation_request()
            if not navigation and request.resource_type not in {
                "stylesheet",
                "script",
                "image",
                "font",
            }:
                raise denied()
            # Only a currently authorized submission may send a POST. Background
            # requests cannot borrow permission after an operation finishes.
            human = (
                request.method != "GET"
                and self.human_authorizer is not None
                and self.human_authorizer(request)
            )
            if not human:
                if request.method != "GET":
                    if self.submission != (request.method, split_url(request.url)):
                        raise denied()
                    self.submission = None
                self.policy.url(request.url, method=request.method, resource=not navigation)
        except (SurfaceError, ValueError, DriverError):
            self.blocked = True
            try:
                await route.abort("blockedbyclient")
            except DriverError:
                pass
            return
        try:
            await route.continue_()
        except DriverError:
            self.blocked = True

    async def websocket(self, socket):
        self.blocked = True
        try:
            await socket.close()
        except DriverError:
            pass

    async def popup(self, page):
        if self.page is not None and page != self.page:
            self.blocked = True
            try:
                await page.close()
            except DriverError:
                pass

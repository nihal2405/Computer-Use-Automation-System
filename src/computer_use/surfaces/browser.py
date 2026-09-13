"""Live browser adapter; contains all Playwright-specific targeting and observation."""

import asyncio
from contextlib import asynccontextmanager
import json
import re
from time import monotonic
from urllib.parse import urlsplit

from playwright.async_api import Error as DriverError, TimeoutError as DriverTimeout
from pydantic import TypeAdapter, ValidationError
import yaml

from computer_use.execution.targeting import bind_references
from computer_use.schemas.action import Condition, action_adapter
from computer_use.schemas.observation import Observation, ObservedControl
from computer_use.surfaces.base import SurfaceError

condition_adapter = TypeAdapter(Condition)
_ROLES = {
    "button", "link", "textbox", "heading", "cell", "row", "table", "region",
    "dialog", "status", "alert", "tab", "tabpanel", "combobox",
}
_STATES = {
    "ready", "loading", "validation_error", "member_not_found", "permission_denied",
    "session_expired", "unexpected_dialog", "application_error", "unknown",
}


class BrowserSurface:
    def __init__(self, page, control, *, base_url, target, run_id, timeout_ms, boundary=None, versions=None):
        self._page = page
        self._control = control
        self._base_url = base_url
        self._identity = target
        self._run_id = run_id
        self._timeout_ms = timeout_ms
        self._sequence = 0
        self._boundary = boundary
        self._versions = frozenset(versions or [target.version])
        self.policy_decision = "not_checked"

    def _authorize(self, action, operation, inputs):
        if self._boundary is not None:
            try:
                self._boundary.check()
                self._boundary.policy.inputs(inputs)
                self._boundary.policy.authorize(action, operation, inputs, self._page.url, self._base_url)
                self.policy_decision = "allowed"
            except SurfaceError as error:
                if error.code == "policy_denied":
                    self.policy_decision = "denied"
                raise

    async def _check_identity(self):
        metadata = await self._page.evaluate("""() => ({
            product: document.documentElement.dataset.product,
            version: document.documentElement.dataset.version,
            state: document.body?.dataset.state
        })""")
        if metadata.get("product") != self._identity.product or metadata.get("version") not in self._versions:
            raise SurfaceError("incompatible_target", "Configured product and version markers", "Missing or incompatible UI identity")
        return metadata

    def _check_boundary(self):
        if self._boundary is not None:
            self._boundary.check()
            self._boundary.policy.url(self._page.url)

    def _budget(self, timeout_ms):
        value = self._timeout_ms if timeout_ms is None else timeout_ms
        if type(value) is not int or not 1 <= value <= 60_000:
            raise SurfaceError("invalid_input", "Timeout between 1 and 60000 ms", "Invalid timeout")
        return value

    @staticmethod
    def _remaining(deadline):
        remaining = (deadline - monotonic()) * 1000
        if remaining <= 0:
            raise SurfaceError("timeout", "Operation within its deadline", "Deadline elapsed")
        return max(1, remaining)

    @asynccontextmanager
    async def _operation(self, timeout_ms, *, inspect_only=False, mutating=False):
        budget = self._budget(timeout_ms)
        deadline = monotonic() + budget / 1000
        try:
            async with asyncio.timeout(budget / 1000):
                async with self._control.access(inspect_only=inspect_only):
                    try:
                        if self._page.is_closed():
                            self._control.mark_closed()
                            self._control.require_open()
                        yield deadline
                    except asyncio.CancelledError:
                        # Cancelling a Python await may leave a browser command alive.
                        # Close its context before releasing ownership if it could act.
                        if mutating:
                            self._control.mark_closed()
                            await asyncio.shield(self._page.context.close())
                        raise
        except (TimeoutError, DriverTimeout):
            raise SurfaceError("timeout", "Operation within its deadline", "Deadline elapsed") from None
        except DriverError as error:
            if self._page.is_closed() or not self._page.context.browser.is_connected():
                self._control.mark_closed()
                raise SurfaceError("session_closed", "A live browser", "Browser or page closed") from None
            # The original message can contain field values, DOM fragments, and URLs.
            code = "ambiguous_target" if "strict mode violation" in str(error) else "browser_error"
            raise SurfaceError(code, "One actionable target on a live page", "Browser operation rejected") from None

    @staticmethod
    def _bind(adapter, value, inputs):
        try:
            validated = adapter.validate_python(value)
            return adapter.validate_python(bind_references(validated, inputs))
        except (ValidationError, TypeError, ValueError):
            raise SurfaceError("invalid_input", "A valid bound operation", "Invalid contract or input") from None

    @staticmethod
    def _css(selector):
        # Never accept Playwright engine chains, XPath, or implicit frame traversal.
        if ">>" in selector or selector.startswith(("xpath=", "text=", "css=", "//")):
            raise SurfaceError("unsupported_target", "A CSS selector in the current document", "Unsupported selector syntax")
        return "css=" + selector

    async def _locate(self, target, *, allow_missing=False):
        root = self._page
        if target.scope:
            root = self._page.locator(self._css(target.scope))
            count = await root.count()
            if count > 1:
                raise SurfaceError("ambiguous_target", "Exactly one scope", "Multiple scopes matched")
            if count == 0:
                if allow_missing:
                    return None
                raise SurfaceError("target_not_found", "Exactly one scope", "Scope is absent")
        if target.strategy == "role":
            locator = root.get_by_role(target.role, name=target.name.value, exact=True)
        elif target.strategy == "label":
            locator = root.get_by_label(target.label.value, exact=True)
        elif target.strategy == "text":
            locator = root.get_by_text(target.text.value, exact=True)
        else:
            locator = root.locator(self._css(target.selector))
        count = await locator.count()
        if count > 1:
            raise SurfaceError("ambiguous_target", "Exactly one target", "Multiple targets matched")
        if count == 0:
            if allow_missing:
                return None
            raise SurfaceError("target_not_found", "Exactly one target", "Target is absent")
        return locator

    async def _evaluate(self, condition, deadline):
        locator = await self._locate(condition.target, allow_missing=True)
        visible = locator is not None and await locator.is_visible()
        if condition.kind == "hidden":
            return not visible
        if condition.kind == "visible":
            return visible
        return visible and (await locator.inner_text(timeout=self._remaining(deadline))).strip() == condition.expected.value

    async def evaluate(self, condition, inputs=None, *, timeout_ms=None, operation=None):
        bound = self._bind(condition_adapter, condition, inputs)
        async with self._operation(timeout_ms, inspect_only=True) as deadline:
            self._authorize(action_adapter.validate_python({"action": "verify", "condition": bound}), operation, inputs)
            result = await self._evaluate(bound, deadline)
            self._check_boundary()
            return result

    async def execute(self, action, inputs=None, *, timeout_ms=None, operation=None):
        self.policy_decision = "not_checked"
        bound = self._bind(action_adapter, action, inputs)
        budget = self._budget(timeout_ms)
        if bound.action == "wait":
            budget = bound.timeout_ms if timeout_ms is None else min(budget, bound.timeout_ms)
        inspecting = bound.action in {"read", "wait", "verify"}
        async with self._operation(budget, inspect_only=inspecting, mutating=not inspecting) as deadline:
            self._authorize(bound, operation, inputs)
            try:
                if self._boundary is not None and self._page.url != "about:blank":
                    await self._check_identity()
                return await self._execute_bound(bound, deadline)
            except DriverError:
                if self._boundary is not None:
                    self._boundary.check()
                raise
            finally:
                if self._boundary is not None:
                    self._boundary.submission = None

    async def _execute_bound(self, bound, deadline):
        result = None
        if bound.action == "navigate":
            await self._page.goto(self._base_url + bound.path, wait_until="domcontentloaded", timeout=self._remaining(deadline))
        elif bound.action == "wait":
            while not await self._evaluate(bound.condition, deadline):
                # Poll observable state, with one deadline across every attempt.
                await asyncio.sleep(min(0.025, self._remaining(deadline) / 1000))
        elif bound.action == "verify":
            if not await self._evaluate(bound.condition, deadline):
                raise SurfaceError("checkpoint_failed", "Checkpoint condition satisfied", "Condition is false")
        else:
            locator = await self._locate(bound.target)
            if self._boundary is not None and bound.action in {"fill", "click"}:
                metadata = await locator.evaluate("""el => ({
                    tag: el.tagName, type: el.type || '', href: el.href || '',
                    download: el.hasAttribute('download'),
                    target: el.getAttribute('formtarget') || el.getAttribute('target') || el.form?.target || '',
                    form_action: el.hasAttribute('formaction') ? el.formAction : (el.form?.action || ''),
                    method: (el.getAttribute('formmethod') || el.form?.method || 'get').toUpperCase(),
                    text: el.innerText || el.getAttribute('aria-label') || ''
                })""", timeout=self._remaining(deadline))
                self._boundary.policy.control(bound, metadata)
                if bound.action == "click" and metadata["tag"] != "A":
                    from computer_use.safety.urls import split_url
                    self._boundary.submission = (metadata["method"], split_url(metadata["form_action"]))
            if bound.action == "click":
                await locator.click(timeout=self._remaining(deadline))
            elif bound.action == "fill":
                await locator.fill(bound.value.value, timeout=self._remaining(deadline))
            else:
                if not await locator.is_visible():
                    raise SurfaceError("target_not_visible", "Visible text", "Target is hidden")
                result = (await locator.inner_text(timeout=self._remaining(deadline))).strip()
        self._check_boundary()
        if self._boundary is not None:
            await self._check_identity()
        return result

    async def observe(self, *, timeout_ms=None):
        async with self._operation(timeout_ms, inspect_only=True) as deadline:
            self._check_boundary()
            metadata = await self._check_identity()
            snapshot = await self._page.locator("body").aria_snapshot(timeout=self._remaining(deadline))
            controls = []
            seen = set()

            # Playwright computes accessible names. Do not invent our own ARIA algorithm.
            def names(tree):
                if isinstance(tree, list):
                    for item in tree:
                        yield from names(item)
                elif isinstance(tree, dict):
                    for key, value in tree.items():
                        yield str(key)
                        yield from names(value)
                elif isinstance(tree, str):
                    yield tree

            for descriptor in names(yaml.safe_load(snapshot)):
                match = re.match(r'^(\w+) ("(?:[^"\\]|\\.)*")', descriptor)
                if not match or match[1] not in _ROLES:
                    continue
                role, name = match[1], json.loads(match[2])
                if not name.strip() or len(name) > 4096 or (role, name) in seen:
                    continue
                seen.add((role, name))
                locator = self._page.get_by_role(role, name=name, exact=True)
                # Discovery observations must not advertise an ambiguous actionable target.
                if await locator.count() != 1 or not await locator.is_visible():
                    continue
                controls.append(ObservedControl(
                    id=f"control_{len(controls)}", visible=True, enabled=await locator.is_enabled(),
                    text=name, target={
                        "strategy": "role", "role": role,
                        "name": {"source": "literal", "value": name},
                        "rationale": "Unique visible role and exact accessible name at observation time",
                    },
                ))
                if len(controls) == 100:
                    break
            self._check_boundary()
            self._sequence += 1
            return Observation(
                schema_version="1.0", run_id=self._run_id,
                session_id=self._control.snapshot.session_id, sequence=self._sequence,
                target=self._identity.model_copy(update={"version": metadata["version"]}), location=urlsplit(self._page.url).path[:4096] or "/",
                summary=snapshot[:4096] if snapshot.strip() else "No accessible content",
                controls=controls, state=metadata.get("state") if metadata.get("state") in _STATES else "unknown",
            )

    async def preview(self, action, inputs, *, operation, timeout_ms=None):
        """Inspect an approved action's target without returning field or cell values."""
        bound = self._bind(action_adapter, action, inputs)
        async with self._operation(timeout_ms, inspect_only=True) as deadline:
            self._authorize(bound, operation, inputs)
            await self._check_identity()
            self._check_boundary()
            if bound.action == "navigate":
                return {"visible": True, "enabled": True}
            if bound.action in {"wait", "verify"}:
                return {"condition_met": await self._evaluate(bound.condition, deadline)}
            locator = await self._locate(bound.target, allow_missing=True)
            visible = locator is not None and await locator.is_visible()
            result = {"visible": visible, "enabled": visible and await locator.is_enabled()}
            if visible and bound.action == "fill":
                # Only compare the approved text field with its already-known input.
                result["filled"] = await locator.evaluate(
                    "(el, value) => el.tagName === 'INPUT' && ['text','search'].includes(el.type) && el.value === value",
                    bound.value.value, timeout=self._remaining(deadline))
            self._check_boundary()
            return result

    async def failure_snapshot(self, *, timeout_ms=1000):
        """Structural DOM only: never collect text, values, URLs, scripts, or attributes."""
        async with self._operation(timeout_ms, inspect_only=True):
            return await self._page.evaluate("""() => {
                let count = 0;
                const tags = new Set('html body main nav header footer section article div p span h1 h2 h3 h4 form label input button a table caption thead tbody tr th td ul ol li dialog select option textarea fieldset legend strong em details summary'.split(' '));
                const roles = new Set('button link textbox heading cell row table region dialog status alert tab tabpanel combobox'.split(' '));
                function visit(el, depth) {
                    if (++count > 500 || depth > 12) return null;
                    const tag = el.tagName.toLowerCase();
                    if (['script', 'style', 'noscript'].includes(tag)) return null;
                    const rect = el.getBoundingClientRect();
                    const role = el.getAttribute('role');
                    return {tag: tags.has(tag) ? tag : 'unknown_tag',
                        role: roles.has(role) ? role : null,
                        visible: !!(rect.width && rect.height), disabled: !!el.disabled,
                        children: Array.from(el.children).map(c => visit(c, depth + 1)).filter(Boolean)};
                }
                return {kind: 'dom_structure', nodes: document.body ? [visit(document.body, 0)] : [], truncated: count > 500};
            }""")

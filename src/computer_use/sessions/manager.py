"""One browser, context, and page survive all operations and ownership changes."""

import asyncio
from uuid import uuid4
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from computer_use.schemas.capability import TargetIdentity
from computer_use.sessions.control import SessionControl
from computer_use.surfaces.base import SurfaceError
from computer_use.surfaces.browser import BrowserSurface


class BrowserSession:
    """Use as an async context manager; default headed mode permits manual takeover.

    All calls belong to one asyncio event loop. No browser objects are exposed to
    automation callers. Closing is explicit, idempotent, and serialized with actions.
    """

    def __init__(
        self, *, base_url: str, target: TargetIdentity, run_id: str,
        headless: bool = False, timeout_ms: int = 5000, policy=None, versions=None,
    ):
        parts = urlsplit(base_url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in {"", "/"}):
            raise ValueError("base_url must be an HTTP(S) origin without credentials")
        self._base_url = base_url.rstrip("/")
        self._target = TargetIdentity.model_validate(target)
        if self._target.surface != "browser":
            raise ValueError("Browser sessions require a browser target")
        if not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 4096:
            raise ValueError("A nonempty run ID of at most 4096 characters is required")
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 60_000:
            raise ValueError("timeout_ms must be an integer from 1 to 60000")
        self._run_id = run_id
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._policy = policy
        self._versions = versions
        self._boundary = None
        self.control = SessionControl(str(uuid4()))
        self._lifecycle = asyncio.Lock()
        self._playwright = self._browser = self._context = self._page = None
        self._surface = None
        self._started = False

    @property
    def session_id(self) -> str:
        return self.control.snapshot.session_id

    @property
    def surface(self) -> BrowserSurface:
        self.control.require_open()
        if self._surface is None:
            raise SurfaceError("session_not_started", "A started browser session", "Start has not completed")
        return self._surface

    async def start(self):
        async with self._lifecycle:
            self.control.require_open()
            if self._started:
                return self
            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=self._headless)
                self._context = await self._browser.new_context(service_workers="block", accept_downloads=False)
                if self._policy is not None:
                    from computer_use.safety.policy import BrowserBoundary
                    self._boundary = BrowserBoundary(self._policy)
                    await self._context.route("**/*", self._boundary.route)
                    await self._context.route_web_socket("**/*", self._boundary.websocket)
                self._page = await self._context.new_page()
                if self._boundary is not None:
                    await self._boundary.attach(self._context, self._page)
                    self._context.on("page", self._boundary.popup)
                self._page.set_default_timeout(self._timeout_ms)
                self._page.on("close", lambda _: self.control.mark_closed())
                self._browser.on("disconnected", lambda _: self.control.mark_closed())
                self._surface = BrowserSurface(
                    self._page, self.control, base_url=self._base_url, target=self._target,
                    run_id=self._run_id, timeout_ms=self._timeout_ms, boundary=self._boundary, versions=self._versions,
                )
                self._started = True
            except BaseException:
                self.control.mark_closed()
                await self._dispose()
                raise
            return self

    async def _dispose(self):
        try:
            if self._browser is not None:
                await self._browser.close()
        finally:
            if self._playwright is not None:
                await self._playwright.stop()

    async def close(self) -> None:
        # Shield cleanup so cancelling a caller cannot orphan a live browser.
        async def cleanup():
            async with self._lifecycle:
                async with self.control.shutdown():
                    await self._dispose()
                    self._playwright = self._browser = self._context = self._page = None

        task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *_):
        await self.close()

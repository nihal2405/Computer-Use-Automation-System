"""Capture browser-originated events as value-free metadata during human ownership."""

import asyncio

from computer_use.observability.evidence import PersistenceError


class HumanCapture:
    def __init__(self, executor):
        self.executor = executor
        self.session = executor._session
        self.count = 0
        self.failed = False
        self.pending = set()
        self.installed = False
        self.on_failure = None

    async def install(self):
        if self.installed:
            return
        self.installed = True
        await self.session._context.expose_binding("__handoffEvent", self._receive)
        script = """(() => {
          let mode = 'AWAITING_HUMAN';
          let pending = new Set();
          const send = payload => {
            const p = window.__handoffEvent(payload); pending.add(p);
            p.finally(() => pending.delete(p)).catch(() => {}); return p;
          };
          window.__handoffMode = value => { mode = value; };
          window.__handoffFlush = () => Promise.allSettled([...pending]);
          for (const kind of ['click','input','change','submit','focusin']) {
            document.addEventListener(kind, event => {
              if (mode === 'RESUME_CHECK' || mode === 'AWAITING_HUMAN') {
                if (kind !== 'focusin') { event.preventDefault(); event.stopImmediatePropagation(); }
                return;
              }
              if (mode !== 'HUMAN_CONTROL' || !event.isTrusted) return;
              const el = event.target instanceof Element ? event.target : null;
              // No text, field value, key, URL, selector, name, ID or attributes leave the page.
              const tag = el?.tagName.toLowerCase();
              send({interaction: kind === 'focusin' ? 'focus' : kind,
                    tag: ['button','a','input','select','textarea','form'].includes(tag) ? tag : 'unknown_tag'});
            }, true);
          }
          send({interaction:'ready'}).then(value => { mode = value; });
        })();"""
        await self.session._context.add_init_script(script)
        await self.session._page.evaluate(script)
        self.session._page.on("framenavigated", self._navigation)

    async def _receive(self, source, payload):
        if source["page"] != self.session._page or source["frame"] != self.session._page.main_frame:
            return "AWAITING_HUMAN"
        state = self.executor.control.state
        if payload == {"interaction": "ready"}:
            return state
        if state != "HUMAN_CONTROL" or self.failed:
            return state
        if (not isinstance(payload, dict) or set(payload) != {"interaction", "tag"}
                or payload["interaction"] not in {"click", "input", "change", "submit", "focus"}
                or payload["tag"] not in {"button", "a", "input", "select", "textarea", "form", "unknown_tag"}):
            return state
        self._record(payload)
        return state

    def _record(self, payload):
        try:
            self.executor.store.event(event="human_interaction", control_state=self.executor.control.state, details=payload)
            self.count += 1
        except PersistenceError:
            self.failed = True
            if self.on_failure:
                self.on_failure()
            task = asyncio.create_task(self.session.close())
            self.pending.add(task)
            task.add_done_callback(self.pending.discard)

    def _navigation(self, frame):
        if frame == self.session._page.main_frame and self.executor.control.state == "HUMAN_CONTROL":
            self._record({"interaction": "navigation"})

    async def mode(self, state):
        if self.failed:
            raise PersistenceError()
        self.session.control.require_open()
        async with asyncio.timeout(5):
            await self.session._page.evaluate("value => window.__handoffMode(value)", state)

    async def flush(self):
        self.session.control.require_open()
        async with asyncio.timeout(5):
            await self.session._page.evaluate("() => window.__handoffFlush()")
        if self.pending:
            await asyncio.gather(*list(self.pending))
        if self.failed:
            raise PersistenceError()

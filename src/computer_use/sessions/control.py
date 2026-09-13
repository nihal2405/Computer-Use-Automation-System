"""Serialize browser access and ownership transfer on one asyncio event loop."""

import asyncio
from contextlib import asynccontextmanager

from computer_use.schemas.intervention import (
    OWNERS, ControlSnapshot, ControlState, ControlTransition,
)
from computer_use.surfaces.base import SurfaceError


class SessionControl:
    def __init__(self, session_id: str):
        self._snapshot = ControlSnapshot(
            session_id=session_id, state="AUTOMATION_RUNNING", owner="automation",
        )
        self._lock = asyncio.Lock()
        self._closed = False
        self.on_transition = None

    @property
    def snapshot(self) -> ControlSnapshot:
        return self._snapshot

    def require_open(self) -> None:
        if self._closed:
            raise SurfaceError("session_closed", "An open browser session", "Session is closed")

    def mark_closed(self) -> None:
        """Called by browser-close events and lifecycle cleanup on the same event loop."""
        self._closed = True

    @asynccontextmanager
    async def access(self, *, inspect_only: bool = False):
        async with self._lock:
            self.require_open()
            state = self._snapshot.state
            if state != "AUTOMATION_RUNNING" and not (inspect_only and state == "RESUME_CHECK"):
                raise SurfaceError(
                    "ownership_denied", "Automation ownership for this operation", state,
                )
            yield

    async def transition(self, state: ControlState, reason: str) -> ControlTransition:
        # Transfer is acknowledged only after an in-flight bounded operation exits.
        async with self._lock:
            # A closed window can still receive a terminal failure record.
            if state != "FAILED":
                self.require_open()
            after = ControlSnapshot(
                session_id=self._snapshot.session_id, state=state, owner=OWNERS.get(state, "none"),
            )
            transition = ControlTransition(before=self._snapshot, after=after, reason=reason)
            if self.on_transition is not None:
                self.on_transition(transition)
            self._snapshot = after
            return transition

    @asynccontextmanager
    async def shutdown(self):
        async with self._lock:
            self.mark_closed()
            yield

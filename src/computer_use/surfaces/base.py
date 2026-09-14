"""Surface interface shared by discovery and replay, independent of the driver."""

from typing import Mapping, Protocol

from computer_use.schemas.action import Action, Condition
from computer_use.schemas.observation import Observation


class SurfaceError(RuntimeError):
    """Stable diagnostics; never include raw driver errors, selectors, or input values."""

    def __init__(self, code: str, expected: str, observed: str):
        self.code = code
        self.expected = expected
        self.observed = observed
        super().__init__(f"{code}: {expected}; {observed}")


class Surface(Protocol):
    async def execute(
        self,
        action: Action,
        inputs: Mapping[str, str] | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> str | None:
        """Execute one validated operation; read returns visible text."""
        ...

    async def observe(self, *, timeout_ms: int | None = None) -> Observation: ...

    async def evaluate(
        self,
        condition: Condition,
        inputs: Mapping[str, str] | None = None,
        *,
        timeout_ms: int | None = None,
    ) -> bool:
        """Check current state once; missing targets are false (true for hidden)."""
        ...

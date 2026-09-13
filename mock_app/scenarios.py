"""Available demo conditions. Their selected state is stored per browser session."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    description: str
    trigger: str


SCENARIOS = MappingProxyType({s.id: s for s in (
    Scenario("normal", "Normal workflow", "Search a member and view their accounts.", "No interruption"),
    Scenario("invalid_input", "Invalid input", "Reject the search even when a valid ID is entered.", "Submit a search"),
    Scenario("missing_member", "Missing member", "Return no matches, including for a known synthetic member.", "Submit a search"),
    Scenario("slow_loading", "Slow loading", "Show a loading screen before search results arrive.", "Submit a search"),
    Scenario("permission_denied", "Permission denial", "Deny access to account information.", "Open Accounts"),
    Scenario("session_expired", "Session expiry", "Ask the operator to restart the demo session once.", "Open Accounts"),
    Scenario("application_error", "Application error", "Show a service-unavailable page instead of account information.", "Open Accounts"),
    Scenario("unexpected_dialog", "Unexpected dialog", "Require a manual acknowledgement before showing accounts.", "Open Accounts"),
)})

"""Synthetic fixtures owned exclusively by the target application, not automation."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class Account:
    kind: str
    last_four: str
    balance: str
    currency: str = "USD"


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    initials: str
    member_since: str
    branch: str
    accounts: tuple[Account, ...]


MEMBERS = MappingProxyType(
    {
        "1001": Member(
            "1001",
            "Avery Morgan",
            "AM",
            "2021",
            "Downtown",
            (Account("Checking", "4101", "342.18"), Account("Savings", "5101", "1250.75")),
        ),
        "2002": Member(
            "2002",
            "Jordan Ellis",
            "JE",
            "2019",
            "Riverside",
            (Account("Checking", "4202", "2290.00"), Account("Savings", "5202", "8040.20")),
        ),
    }
)

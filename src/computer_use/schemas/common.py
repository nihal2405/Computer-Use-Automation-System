"""Shared strict, JSON-compatible contract primitives."""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]
Text = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"\S")]
Version = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")]
Scalar = StrictStr | StrictInt | StrictBool


class Contract(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True,
        hide_input_in_errors=True, revalidate_instances="always",
    )


class ValueSpec(Contract):
    """All declared inputs and outputs are required in schema version 1.0."""

    type: Literal["string", "integer", "boolean", "decimal_string", "currency_code"]
    description: Text

    def check(self, value: object) -> None:
        valid = {
            "string": lambda: type(value) is str and bool(value.strip()),
            "integer": lambda: type(value) is int,
            "boolean": lambda: type(value) is bool,
            "decimal_string": lambda: type(value) is str
            and re.fullmatch(r"-?(?:0|[1-9][0-9]*)\.[0-9]+", value) is not None,
            "currency_code": lambda: type(value) is str
            and re.fullmatch(r"[A-Z]{3}", value) is not None,
        }[self.type]()
        if not valid:
            raise ValueError(f"Value does not match declared type {self.type}")


def check_values(specs: dict[str, ValueSpec], values: dict[str, Scalar]) -> None:
    """Check exact keys and strict value types, without echoing submitted values."""
    if type(values) is not dict or set(values) != set(specs):
        raise ValueError("Values must contain exactly the declared names")
    for name, spec in specs.items():
        spec.check(values[name])

"""Serializable actions and deterministic target descriptions; no UI execution."""

from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit

from pydantic import Field, TypeAdapter, field_validator

from computer_use.schemas.common import Contract, Identifier, Text


class LiteralText(Contract):
    source: Literal["literal"]
    value: Text


class InputReference(Contract):
    source: Literal["input"]
    ref: Annotated[str, Field(pattern=r"^inputs\.[a-z][a-z0-9_]{0,63}$")]


TextValue = Annotated[LiteralText | InputReference, Field(discriminator="source")]


class TargetBase(Contract):
    rationale: Text
    scope: Text | None = None  # Optional CSS scope, resolved by the browser adapter.


class RoleTarget(TargetBase):
    strategy: Literal["role"]
    role: Literal[
        "button", "link", "textbox", "heading", "cell", "row", "table",
        "region", "dialog", "status", "alert", "tab", "tabpanel", "combobox",
    ]
    name: TextValue


class LabelTarget(TargetBase):
    strategy: Literal["label"]
    label: TextValue


class TextTarget(TargetBase):
    strategy: Literal["text"]
    text: TextValue


class CssTarget(TargetBase):
    strategy: Literal["css"]
    selector: Text


Target = Annotated[
    RoleTarget | LabelTarget | TextTarget | CssTarget, Field(discriminator="strategy")
]


class Visible(Contract):
    kind: Literal["visible"]
    target: Target


class Hidden(Contract):
    kind: Literal["hidden"]
    target: Target


class TextEquals(Contract):
    kind: Literal["text_equals"]
    target: Target
    expected: TextValue


Condition = Annotated[Visible | Hidden | TextEquals, Field(discriminator="kind")]
Timeout = Annotated[int, Field(ge=1, le=60_000)]


class Navigate(Contract):
    action: Literal["navigate"]
    path: Text

    @field_validator("path")
    @classmethod
    def relative_application_path(cls, value: str) -> str:
        # Decode for validation to reject encoded authority, traversal, or separators.
        decoded = value
        for _ in range(4):
            new = unquote(decoded)
            if new == decoded:
                break
            decoded = new
        parts = urlsplit(decoded)
        if (
            not decoded.startswith("/") or decoded.startswith("//")
            or parts.scheme or parts.netloc or parts.query or parts.fragment
            or "\\" in decoded or "%" in decoded
            or any(part in (".", "..") for part in parts.path.split("/"))
            or any(character.isspace() or ord(character) < 32 for character in decoded)
        ):
            raise ValueError("Navigation requires an absolute application path without query or fragment")
        return value


class Fill(Contract):
    action: Literal["fill"]
    target: Target
    value: TextValue


class Click(Contract):
    action: Literal["click"]
    target: Target


class Read(Contract):
    action: Literal["read"]
    target: Target
    output: Identifier


class Wait(Contract):
    action: Literal["wait"]
    condition: Condition
    timeout_ms: Timeout


class Verify(Contract):
    action: Literal["verify"]
    condition: Condition


Action = Annotated[Navigate | Fill | Click | Read | Wait | Verify, Field(discriminator="action")]
action_adapter = TypeAdapter(Action)
target_adapter = TypeAdapter(Target)


def input_references(value: object) -> list[InputReference]:
    """Find explicit references, including those inside targets and conditions."""
    if isinstance(value, InputReference):
        return [value]
    if isinstance(value, Contract):
        children = [getattr(value, name) for name in type(value).model_fields]
    elif isinstance(value, dict):
        children = list(value.values())
    elif isinstance(value, list):
        children = value
    else:
        return []
    return [reference for child in children for reference in input_references(child)]

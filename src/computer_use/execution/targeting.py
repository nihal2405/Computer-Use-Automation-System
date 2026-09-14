"""Bind explicit input references without interpreting UI strings as templates."""

from collections.abc import Mapping

from pydantic import BaseModel

from computer_use.surfaces.base import SurfaceError


def bind_references(contract: BaseModel, inputs: Mapping[str, str] | None) -> dict:
    values = dict(inputs or {})

    def bind(value):
        if isinstance(value, dict):
            if value.get("source") == "input":
                name = value["ref"].removeprefix("inputs.")
                if name not in values or type(values[name]) is not str:
                    raise SurfaceError(
                        "invalid_input",
                        "A string for every referenced input",
                        "Missing or invalid input",
                    )
                return {"source": "literal", "value": values[name]}
            return {key: bind(item) for key, item in value.items()}
        if isinstance(value, list):
            return [bind(item) for item in value]
        return value

    return bind(contract.model_dump())

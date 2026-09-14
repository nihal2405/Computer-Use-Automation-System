"""Strict, explicit loading of operator-owned YAML; no model-supplied policies."""

import re
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import Field, field_validator, model_validator

from computer_use.safety.urls import split_url
from computer_use.schemas.action import Condition, Target, TextValue
from computer_use.schemas.common import Contract, Identifier, Text


class ConfigurationError(ValueError):
    pass


class BrowserSettings(Contract):
    headless: bool = False


class RuntimeSettings(Contract):
    max_steps: Annotated[int, Field(ge=1, le=100)] = 30
    run_timeout_seconds: Annotated[int, Field(ge=1, le=3600)] = 120
    step_timeout_seconds: Annotated[int, Field(ge=1, le=60)] = 10
    max_retries: Annotated[int, Field(ge=0, le=3)] = 2
    max_no_progress_steps: Annotated[int, Field(ge=1, le=100)] = 3
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    artifact_directory: str = "artifacts"
    run_directory: str = "runs"

    @field_validator("artifact_directory", "run_directory")
    @classmethod
    def relative_directory(cls, value):
        path = Path(value)
        if not value.strip() or path.is_absolute() or ".." in path.parts:
            raise ValueError("Output directories must be relative to the project")
        return value


class TargetSettings(Contract):
    target_id: Identifier
    product: Identifier
    supported_versions: Annotated[list[Text], Field(min_length=1)]
    entry_url: Text
    surface: Literal["browser"]
    locator_overrides: dict = Field(default_factory=dict)

    @field_validator("entry_url")
    @classmethod
    def valid_entry(cls, value):
        split_url(value)
        return value

    @field_validator("locator_overrides")
    @classmethod
    def no_unimplemented_overrides(cls, value):
        if value:
            raise ValueError("Locator overrides are not supported yet; edit reviewed policy rules")
        return value


def validate_pattern(value: str) -> str:
    if not value.startswith("^") or not value.endswith("$"):
        raise ValueError("Patterns must be anchored")
    re.compile(value)
    return value


class RequestRule(Contract):
    path: Text
    methods: Annotated[list[Literal["GET", "POST"]], Field(min_length=1)]

    _pattern = field_validator("path")(validate_pattern)


class ActionRule(Contract):
    operation: Identifier
    action: Literal["navigate", "fill", "click", "read", "wait", "verify"]
    target: Target | None = None
    condition: Condition | None = None
    path: Text | None = None
    value: TextValue | None = None

    @model_validator(mode="after")
    def complete_rule(self) -> Self:
        if self.action == "navigate":
            if self.path is None or any(
                x is not None for x in (self.target, self.condition, self.value)
            ):
                raise ValueError("Navigation rule requires only a path pattern")
            validate_pattern(self.path)
        elif self.action in {"wait", "verify"}:
            if self.condition is None or any(
                x is not None for x in (self.target, self.path, self.value)
            ):
                raise ValueError("Condition rule requires only a condition")
        elif (
            self.target is None
            or self.condition is not None
            or self.path is not None
            or (self.action == "fill") != (self.value is not None)
        ):
            raise ValueError("Target/value fields do not match the action")
        return self


class HumanRequestRule(Contract):
    path: Text
    method: Literal["POST"] = "POST"
    fields: dict[Identifier, Text]
    ignored_fields: list[Identifier] = Field(default_factory=list)

    _pattern = field_validator("path")(validate_pattern)


class PolicySettings(Contract):
    default_decision: Literal["deny"]
    risky_action_decision: Literal["block"]
    allowed_origins: Annotated[list[Text], Field(min_length=1)]
    navigation: Annotated[list[RequestRule], Field(min_length=1)]
    resources: list[RequestRule] = Field(default_factory=list)
    input_patterns: dict[Identifier, Text] = Field(default_factory=dict)
    rules: Annotated[list[ActionRule], Field(min_length=1)]
    human_requests: list[HumanRequestRule] = Field(default_factory=list)

    @field_validator("allowed_origins")
    @classmethod
    def origins_only(cls, values):
        for value in values:
            _, path = split_url(value)
            if path != "/":
                raise ValueError("Allowed origins cannot contain paths")
        return values

    @field_validator("input_patterns")
    @classmethod
    def input_regexes(cls, values):
        for value in values.values():
            validate_pattern(value)
        return values


class Configuration(Contract):
    runtime: RuntimeSettings
    target: TargetSettings
    policy: PolicySettings

    @model_validator(mode="after")
    def compatible_entry(self) -> Self:
        origin, path = split_url(self.target.entry_url)
        if origin not in {split_url(value)[0] for value in self.policy.allowed_origins}:
            raise ValueError("Entry origin is not approved")
        if not any(
            "GET" in r.methods and re.fullmatch(r.path, path) for r in self.policy.navigation
        ):
            raise ValueError("Entry route is not approved")
        return self


class _UniqueLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("Duplicate YAML key")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def load_configuration(project_root: Path) -> Configuration:
    try:

        def read(name):
            path = project_root / "config" / name
            if path.stat().st_size > 131072:
                raise ValueError("Configuration too large")
            return yaml.load(path.read_text(), Loader=_UniqueLoader)

        return Configuration(
            runtime=read("settings.yaml"),
            target=read("targets/mock_bank.yaml"),
            policy=read("policy.yaml"),
        )
    except (OSError, ValueError, TypeError, yaml.YAMLError, re.error):
        # Never echo YAML content or file paths that might include secrets.
        raise ConfigurationError("Configuration is missing, invalid, or incompatible") from None

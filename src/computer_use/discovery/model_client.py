"""Structured OpenAI/Gemini transports with fixed endpoints and no hidden retries."""

from dataclasses import dataclass
import json
import os
from typing import Annotated, Literal

from dotenv import dotenv_values
from openai import AsyncOpenAI, APIError, APITimeoutError
from pydantic import Field, ValidationError
import yaml

from computer_use.discovery.contracts import Decision, response_schema
from computer_use.discovery.prompts import SYSTEM
from computer_use.schemas.common import Contract, Text
from computer_use.settings import _UniqueLoader


class ModelSettings(Contract):
    provider: Literal["openai", "gemini"]
    model: Text
    request_timeout_seconds: Annotated[int, Field(ge=1, le=120)] = 30
    max_output_tokens: Annotated[int, Field(ge=256, le=8000)] = 2500
    reasoning_effort: Literal["none", "low", "medium", "high"] = "low"


class ModelError(RuntimeError):
    def __init__(self, code, *, provider_status=None, provider_reason=None):
        self.code = code
        self.provider_status = provider_status
        self.provider_reason = provider_reason
        super().__init__(code)  # Never expose provider exceptions, prompts, or credentials.


@dataclass(frozen=True)
class ModelReply:
    decision: Decision
    response_id: str
    model: str


class OpenAIModel:
    def __init__(self, settings, api_key):
        if not api_key or not api_key.strip():
            raise ModelError("model_credentials_missing")
        self.settings = ModelSettings.model_validate(settings)
        endpoint = {"openai": "https://api.openai.com/v1",
                    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/"}[self.settings.provider]
        self._client = AsyncOpenAI(api_key=api_key, base_url=endpoint,
                                  max_retries=0, timeout=settings.request_timeout_seconds)

    @classmethod
    def from_project(cls, root):
        try:
            path = root / "config/discovery.yaml"
            if path.stat().st_size > 131072:
                raise ValueError()
            settings = ModelSettings.model_validate(yaml.load(path.read_text(), Loader=_UniqueLoader))
            key_name = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}[settings.provider]
            key = os.environ.get(key_name) or dotenv_values(root / ".env").get(key_name)
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            raise ModelError("invalid_model_configuration") from None
        return cls(settings, key)

    async def decide(self, context):
        try:
            if self.settings.provider == "gemini":
                response = await self._client.chat.completions.create(
                    model=self.settings.model, max_tokens=self.settings.max_output_tokens,
                    reasoning_effort=self.settings.reasoning_effort,
                    messages=[{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": json.dumps(context)}],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "ui_decision", "strict": True, "schema": response_schema()}},
                )
                if (not response.choices or response.choices[0].finish_reason != "stop"
                        or response.choices[0].message.refusal or not response.choices[0].message.content):
                    raise ModelError("invalid_model_response")
                decision = Decision.model_validate_json(response.choices[0].message.content)
                return ModelReply(decision, response.id, response.model)
            response = await self._client.responses.create(
                model=self.settings.model, store=False, max_output_tokens=self.settings.max_output_tokens,
                input=[{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": json.dumps(context)}],
                text={"format": {"type": "json_schema", "name": "ui_decision", "strict": True,
                                 "schema": response_schema()}},
            )
            if response.status != "completed" or not response.output_text:
                raise ModelError("invalid_model_response")
            decision = Decision.model_validate_json(response.output_text)
            return ModelReply(decision, response.id, response.model)
        except APITimeoutError:
            raise ModelError("timeout") from None
        except APIError as error:
            known = {"invalid_json_schema", "insufficient_quota", "invalid_api_key", "model_not_found",
                     "rate_limit_exceeded", "unsupported_value", "invalid_request_error"}
            reason = getattr(error, "code", None)
            if reason not in known:
                # Classify only fixed phrases; never propagate raw provider text.
                message = str(error).lower()
                if "quota" in message or "billing" in message or "credit" in message:
                    reason = "insufficient_quota"
                elif "rate limit" in message or "rate_limit" in message:
                    reason = "rate_limit_exceeded"
            raise ModelError("model_request_failed", provider_status=getattr(error, "status_code", None),
                             provider_reason=reason if reason in known else "provider_error") from None
        except (ValidationError, ValueError, TypeError):
            raise ModelError("invalid_model_response") from None

    async def close(self):
        await self._client.close()

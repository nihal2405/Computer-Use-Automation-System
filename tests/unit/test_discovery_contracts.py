import asyncio
import json
from pathlib import Path

import httpx
from openai import AsyncOpenAI
import pytest

from computer_use.capabilities.compiler import compile_capability
from computer_use.capabilities.store import CapabilityStore
from computer_use.discovery.contracts import Decision, DiscoveryTask, response_schema
from computer_use.discovery.model_client import ModelError, ModelSettings, OpenAIModel
from computer_use.discovery.recorder import Recorder
from computer_use.execution.executor import StepOutcome
from computer_use.schemas.capability import Step, TargetIdentity

ROOT = Path(__file__).parents[2]


def test_discovery_task_contains_no_sequence_or_fixture_provenance():
    task = DiscoveryTask.model_validate_json((ROOT / "config/tasks/read_savings_balance.json").read_text())
    assert not hasattr(task, "steps") and not hasattr(task, "provenance")
    with pytest.raises(ValueError):
        DiscoveryTask.model_validate({**task.model_dump(), "steps": []})


@pytest.mark.parametrize("decision", [
    {"command": "shell", "step": None, "explanation": "Bad command"},
    {"command": "act", "step": None, "explanation": "Missing step"},
    {"command": "complete", "step": None, "explanation": "Done", "outputs": {"balance": "100"}},
])
def test_model_decisions_are_strict(decision):
    with pytest.raises(ValueError):
        Decision.model_validate(decision)


def test_provider_schema_uses_required_fields_and_supported_unions():
    def inspect(value):
        if isinstance(value, dict):
            assert "oneOf" not in value and "discriminator" not in value and "default" not in value
            if value.get("type") == "object":
                assert value["additionalProperties"] is False
                assert set(value["required"]) == set(value["properties"])
            for item in value.values():
                inspect(item)
        if isinstance(value, list):
            for item in value:
                inspect(item)
    inspect(response_schema())


def test_bindings_come_from_templates_not_global_string_replacement():
    template = CapabilityStore.load(ROOT / "tests/fixtures/read_savings_balance.json").steps[1]
    recorder = Recorder([template], {"member_id": "1001"})
    literal = template.model_dump()
    literal["action"]["value"] = {"source": "literal", "value": "1001"}
    literal["action"]["target"]["rationale"] = "1001 should never become a reference here"
    normalized = recorder.normalize(Step.model_validate(literal))
    assert normalized.action.value.ref == "inputs.member_id"
    assert normalized.action.target.rationale == template.action.target.rationale
    assert "1001" not in normalized.model_dump_json()
    with pytest.raises(ValueError):
        recorder.append(normalized, StepOutcome(status="failure", step_id=normalized.id))


@pytest.mark.parametrize("failure", ["unverified", "no_model"])
def test_compiler_rejects_unverified_or_non_model_execution(failure):
    task = DiscoveryTask.model_validate_json((ROOT / "config/tasks/read_savings_balance.json").read_text())
    cap = CapabilityStore.load(ROOT / "tests/fixtures/read_savings_balance.json")
    recorder = Recorder(cap.steps, {"member_id": "1001"})
    recorder.steps = cap.steps
    recorder.model_responses = ["response"] if failure != "no_model" else []
    with pytest.raises(ValueError):
        compile_capability(task, recorder, run_id="untrusted", identity=TargetIdentity(product="synthetic_bank", version="1.0", surface="browser"),
            outputs={"balance": "1250.75", "currency": "USD"}, checkpoint_verified=failure != "unverified", live_provider=False)


@pytest.mark.parametrize(("mode", "code"), [("ok", None), ("refusal", "invalid_model_response"),
    ("incomplete", "invalid_model_response"), ("malformed", "invalid_model_response"), ("http_error", "model_request_failed")])
def test_openai_transport_structured_output_errors_and_no_hidden_retries(mode, code):
    async def run():
        requests = []
        def handler(request):
            requests.append(json.loads(request.content))
            if mode == "http_error":
                return httpx.Response(429, json={"error": {"message": "private-provider-details", "type": "rate_limit"}})
            output_text = json.dumps({"command": "complete", "step": None, "explanation": "Verified by controller"})
            content = [{"type": "output_text", "text": "{" if mode == "malformed" else output_text, "annotations": []}]
            if mode == "refusal":
                content = [{"type": "refusal", "refusal": "private-provider-details"}]
            return httpx.Response(200, json={"id": "resp_test", "object": "response", "created_at": 1,
                "model": "gpt-4.1-mini-2025-04-14", "status": "incomplete" if mode == "incomplete" else "completed",
                "output": [{"id": "msg_test", "type": "message", "role": "assistant", "status": "completed", "content": content}]})
        settings = ModelSettings(provider="openai", model="gpt-4.1-mini-2025-04-14")
        model = OpenAIModel(settings, "fake-test-key")
        await model.close()
        model._client = AsyncOpenAI(api_key="fake-test-key", max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            if code:
                with pytest.raises(ModelError) as error:
                    await model.decide({"state": "ready"})
                assert str(error.value) == code and "private" not in str(error.value)
            else:
                assert (await model.decide({"state": "ready"})).decision.command == "complete"
            assert len(requests) == 1
            assert requests[0]["store"] is False
            assert requests[0]["text"]["format"]["strict"] is True
            assert "fake-test-key" not in json.dumps(requests)
        finally:
            await model.close()
    asyncio.run(run())


def test_missing_credentials_fail_without_network(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/discovery.yaml").write_text((ROOT / "config/discovery.yaml").read_text())
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ModelError, match="model_credentials_missing"):
        OpenAIModel.from_project(tmp_path)


def test_live_provenance_export_preserves_generated_run_correlation(tmp_path):
    from uuid import uuid4
    from computer_use.safety.policy import Policy
    from computer_use.safety.redaction import Redactor
    from computer_use.settings import load_configuration
    run_id = str(uuid4())
    cap = CapabilityStore.load(ROOT / "tests/fixtures/read_savings_balance.json")
    data = cap.model_dump()
    data.update(provenance="llm_discovery", discovery_run_id=run_id)
    settings = load_configuration(ROOT)
    store = CapabilityStore(tmp_path, Redactor(Policy(settings.policy).vocabulary() | {settings.target.product, *settings.target.supported_versions}))
    saved = CapabilityStore.load(store.save(data))
    assert saved.discovery_run_id == run_id


@pytest.mark.parametrize(("finish", "text", "accepted"), [("stop", '{"command":"complete","step":null,"explanation":"Check completion"}', True),
    ("length", "{}", False), ("stop", "{", False), ("content_filter", "", False)])
def test_gemini_uses_google_endpoint_and_validates_structured_response(finish, text, accepted):
    async def run():
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"id": "chatcmpl_test", "object": "chat.completion", "created": 1,
                "model": "gemini-3.8-flash", "choices": [{"index": 0, "finish_reason": finish,
                    "message": {"role": "assistant", "content": text}}]})
        model = OpenAIModel(ModelSettings(provider="gemini", model="gemini-3.8-flash"), "fake-gemini-key")
        endpoint = str(model._client.base_url)
        await model.close()
        model._client = AsyncOpenAI(api_key="fake-gemini-key", base_url=endpoint, max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            if accepted:
                assert (await model.decide({"state": "ready"})).decision.command == "complete"
            else:
                with pytest.raises(ModelError, match="invalid_model_response"):
                    await model.decide({"state": "ready"})
            assert len(requests) == 1
            assert requests[0].url.host == "generativelanguage.googleapis.com"
            assert requests[0].url.path == "/v1beta/openai/chat/completions"
            assert json.loads(requests[0].content)["response_format"]["type"] == "json_schema"
            assert "fake-gemini-key" not in requests[0].content.decode()
        finally:
            await model.close()
    asyncio.run(run())


def test_gemini_never_falls_back_to_openai_credentials(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/discovery.yaml").write_text("provider: gemini\nmodel: gemini-3.8-flash\n")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ModelError, match="model_credentials_missing"):
        OpenAIModel.from_project(tmp_path)

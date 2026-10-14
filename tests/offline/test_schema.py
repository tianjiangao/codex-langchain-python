# SPDX-License-Identifier: Apache-2.0
# Adapter assertions adapted from original tests; generic schema fixtures are new.
"""OFFLINE schema/validator fixtures, never claimed as investment evidence."""

import copy
import json

import pytest
from jsonschema import ValidationError as JSONValidationError
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field, ValidationError, field_validator

from langchain_codex_sdk.chat_models import ChatCodexSDK
from langchain_codex_sdk.schema import (
    CodexTurnError,
    SchemaCompatibilityError,
    describe_turn_failure,
    encode_business_value,
    normalize_output_schema,
    validate_wire,
)
from tests.fixtures import DecisionSpec, NumericSpec, PlanSpec, ScoreSpec, render_value

RESEARCH = {"recommendation": "C", "rationale": "OFFLINE", "strategic_actions": "OFFLINE"}
TRADER = {
    "action": "C",
    "reasoning": "OFFLINE",
    "amount": None,
    "threshold": None,
    "note": None,
}
PORTFOLIO = {
    "rating": "C",
    "executive_summary": "OFFLINE",
    "investment_thesis": "OFFLINE",
    "target": None,
    "horizon": None,
}
SENTIMENT = {
    "overall_band": "Neutral",
    "overall_score": 5.0,
    "confidence": "low",
    "narrative": "OFFLINE",
}
CASES = [
    (PlanSpec, RESEARCH),
    (NumericSpec, TRADER),
    (DecisionSpec, PORTFOLIO),
    (ScoreSpec, SENTIMENT),
]


@pytest.mark.parametrize("model,payload", CASES)
def test_all_original_schemas_normalized_without_mutation(model, payload):
    original = model.model_json_schema()
    before = copy.deepcopy(original)
    mapping = normalize_output_schema(original)
    assert original == before == mapping.original
    assert list(mapping.wire["properties"]) == list(original["properties"])
    assert set(mapping.wire["required"]) == set(original["properties"])
    assert mapping.wire["additionalProperties"] is False
    assert mapping.wire.get("$defs") == original.get("$defs")
    for name, field in original["properties"].items():
        expected = {k: v for k, v in field.items() if k != "default"}
        converted = mapping.wire["properties"][name]
        if "$ref" in expected and len(expected) > 1:
            target = original["$defs"][expected["$ref"].split("/")[-1]]
            assert "$ref" not in converted and converted["enum"] == target["enum"]
            assert converted["type"] == target["type"]
            assert expected["description"] in converted["description"]
            assert target["description"] in converted["description"]
        else:
            assert converted == expected
    validate_wire(payload, mapping.wire)


@pytest.mark.parametrize(
    "model,payload,renderer",
    [
        (NumericSpec, TRADER, render_value),
        (DecisionSpec, PORTFOLIO, render_value),
    ],
)
@pytest.mark.parametrize("omit", [True, False])
def test_missing_and_null_preserve_business_value_and_renderer(model, payload, renderer, omit):
    raw = {k: v for k, v in payload.items() if v is not None} if omit else dict(payload)
    encoded, changes = encode_business_value(model, raw)
    assert encoded == model.model_validate(raw).model_dump(mode="json")
    assert renderer(model.model_validate(encoded)) == renderer(model.model_validate(raw))
    assert set(encoded) == set(model.model_fields)
    if omit:
        assert changes and all(not c["before_present"] and c["after"] is None for c in changes)
        # Value/render equivalence, not equality of Pydantic field-presence provenance.
        assert (
            model.model_validate(encoded).model_fields_set
            != model.model_validate(raw).model_fields_set
        )
    else:
        assert not changes


VALID = CASES + [
    (NumericSpec, {**TRADER, "amount": 189.5}),
    (DecisionSpec, {**PORTFOLIO, "target": 210.25, "horizon": "3-6 months"}),
]


@pytest.mark.parametrize("model,payload", VALID)
def test_adapter_native_mock_roundtrip_original_pydantic(model, payload, monkeypatch):
    sent = []

    def invoke(*args, **kwargs):
        sent.append(kwargs)
        return AIMessage(content=json.dumps(payload))

    monkeypatch.setattr(ChatCodexSDK, "invoke", invoke)
    llm = ChatCodexSDK()
    parsed = llm.with_structured_output(model, include_raw=True).invoke("OFFLINE")
    assert isinstance(parsed["parsed"], model) and parsed["parsing_error"] is None
    assert parsed["parsed"].model_dump(mode="json") == model.model_validate(payload).model_dump(
        mode="json"
    )
    assert sent[0]["codex_output_schema"] == normalize_output_schema(model.model_json_schema()).wire
    assert llm.structured_evidence[0]["status"] == "PASS"
    assert llm.structured_evidence[0]["raw_payload"] == payload
    assert not llm.fallback_evidence


@pytest.mark.parametrize(
    "model,payload",
    [
        (NumericSpec, {k: v for k, v in TRADER.items() if v is not None}),
        (DecisionSpec, {k: v for k, v in PORTFOLIO.items() if v is not None}),
    ],
)
def test_native_model_omission_is_not_silently_defaulted(model, payload, monkeypatch):
    monkeypatch.setattr(
        ChatCodexSDK, "invoke", lambda *a, **k: AIMessage(content=json.dumps(payload))
    )
    llm = ChatCodexSDK()
    with pytest.raises(JSONValidationError):
        llm.with_structured_output(model).invoke("OFFLINE")
    assert llm.structured_evidence[0]["phase"] == "wire_response_validation"
    assert llm.structured_evidence[0]["status"] == "FAIL"


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (NumericSpec, TRADER, "amount"),
        (NumericSpec, TRADER, "threshold"),
        (DecisionSpec, PORTFOLIO, "target"),
    ],
)
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("189.5", 189.5),
        ("$1,234.50", 1234.5),
        ("15%", None),
        ("None", None),
        ("150-160", None),
        ("around 150", None),
        (None, None),
        (123, 123.0),
    ],
)
def test_fixture_float_validators_preserved_and_logged(model, payload, field, raw, expected):
    fixture = {**payload, field: raw}
    assert getattr(model.model_validate(fixture), field) == expected
    encoded, changes = encode_business_value(model, fixture)
    assert encoded[field] == expected
    if raw != expected or type(raw) is not type(expected):
        assert any(
            c["path"] == f"$.{field}" and c["before"] == raw and c["after"] == expected
            for c in changes
        )


@pytest.mark.parametrize("value", [-1.0, 0.0, 189.5])
def test_no_invented_numeric_positivity_rule(value):
    # The fixture schema has no ge=0 price constraint. Do not invent one.
    encoded, _ = encode_business_value(NumericSpec, {**TRADER, "amount": value})
    assert encoded["amount"] == value


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (NumericSpec, TRADER, "amount"),
        (NumericSpec, TRADER, "threshold"),
        (DecisionSpec, PORTFOLIO, "target"),
    ],
)
@pytest.mark.parametrize("value", ["189.5", "15%"])
def test_native_wire_numeric_strings_or_percent_fail_without_loss(
    model, payload, field, value, monkeypatch
):
    raw = {**payload, field: value}
    monkeypatch.setattr(ChatCodexSDK, "invoke", lambda *a, **k: AIMessage(content=json.dumps(raw)))
    llm = ChatCodexSDK()
    with pytest.raises(JSONValidationError):
        llm.with_structured_output(model).invoke("OFFLINE")
    event = llm.structured_evidence[0]
    assert event["raw_payload"][field] == value
    assert event["pydantic_value_changes"] and event["phase"] == "wire_response_validation"


@pytest.mark.parametrize(
    "value,valid", [(-1, False), (0, True), (5, True), (10, True), (11, False)]
)
def test_sentiment_bounds_unchanged(value, valid):
    mapping = normalize_output_schema(ScoreSpec.model_json_schema())
    if valid:
        encode_business_value(ScoreSpec, {**SENTIMENT, "overall_score": value})
    else:
        with pytest.raises(ValidationError):
            ScoreSpec.model_validate({**SENTIMENT, "overall_score": value})
        with pytest.raises(JSONValidationError):
            validate_wire({**SENTIMENT, "overall_score": value}, mapping.wire)


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (PlanSpec, RESEARCH, "recommendation"),
        (NumericSpec, TRADER, "action"),
        (DecisionSpec, PORTFOLIO, "rating"),
        (ScoreSpec, SENTIMENT, "overall_band"),
        (ScoreSpec, SENTIMENT, "confidence"),
    ],
)
def test_enum_and_literal_invalid_original_pydantic_rejects(model, payload, field, monkeypatch):
    monkeypatch.setattr(
        ChatCodexSDK,
        "invoke",
        lambda *a, **k: AIMessage(content=json.dumps({**payload, field: "INVALID"})),
    )
    llm = ChatCodexSDK()
    with pytest.raises(ValidationError):
        llm.with_structured_output(model).invoke("OFFLINE")
    assert llm.structured_evidence[0]["phase"] == "pydantic_validation"


def test_unknown_supplied_fields_never_dropped():
    with pytest.raises(SchemaCompatibilityError, match="drop supplied fields"):
        encode_business_value(NumericSpec, {**TRADER, "unexpected": "keep-me"})
    with pytest.raises(JSONValidationError):
        validate_wire(
            {**TRADER, "unexpected": "keep-me"},
            normalize_output_schema(NumericSpec.model_json_schema()).wire,
        )


@pytest.mark.parametrize(
    "field",
    [
        {"type": "string"},
        {"type": ["string", "null"], "default": "non-null-default"},
        {"type": "number", "default": None},
    ],
)
def test_unsupported_optional_defaults_blocked_before_model(field):
    model = ChatCodexSDK()
    with pytest.raises(SchemaCompatibilityError):
        model.with_structured_output({"type": "object", "properties": {"x": field}, "required": []})
    assert model.structured_evidence[0]["status"] == "BLOCKED"


def test_arbitrary_maps_external_refs_and_nonfinite_blocked():
    for schema in [
        {"type": "object", "additionalProperties": True},
        {"$ref": "https://example.invalid/schema.json"},
    ]:
        with pytest.raises(SchemaCompatibilityError):
            normalize_output_schema(schema)
    with pytest.raises(SchemaCompatibilityError, match="Non-finite"):
        encode_business_value(NumericSpec, {**TRADER, "amount": float("nan")})


def test_nested_nullable_refs_and_defaults_are_converted():
    class Inner(BaseModel):
        value: float | None = None

    class Outer(BaseModel):
        inner: Inner

    encoded, changes = encode_business_value(Outer, {"inner": {}})
    assert encoded == {"inner": {"value": None}} and changes
    mapping = normalize_output_schema(Outer.model_json_schema())
    assert mapping.wire["$defs"]["Inner"]["required"] == ["value"]


def test_pydantic_field_validator_runs_even_when_json_schema_passes(monkeypatch):
    class Even(BaseModel):
        value: int = Field(ge=0)

        @field_validator("value")
        @classmethod
        def even(cls, value):
            if value % 2:
                raise ValueError("OFFLINE_ODD")
            return value

    monkeypatch.setattr(ChatCodexSDK, "invoke", lambda *a, **k: AIMessage(content='{"value":3}'))
    with pytest.raises(ValidationError, match="OFFLINE_ODD"):
        ChatCodexSDK().with_structured_output(Even).invoke("OFFLINE")


@pytest.mark.parametrize(
    "code,category",
    [
        ("invalid_json_schema", "SERVER_SCHEMA_REJECTED"),
        ("unsupported_response_format", "STRUCTURED_MODE_UNSUPPORTED"),
        ("context_length_exceeded", "CONTEXT_OR_THREAD_STATE"),
        ("thread_not_found", "CONTEXT_OR_THREAD_STATE"),
        ("other", "SDK_TURN_FAILURE"),
    ],
)
def test_original_service_error_code_stage_preserved(code, category):
    turn = {
        "status": "failed",
        "error": {
            "message": json.dumps(
                {
                    "status": 400,
                    "error": {
                        "type": "invalid_request_error",
                        "param": "text.format.schema",
                        "code": code,
                    },
                }
            )
        },
    }
    error = CodexTurnError(turn)
    assert isinstance(error, RuntimeError)
    assert error.failure == describe_turn_failure(turn)
    assert error.failure["category"] == category and error.failure["http_status"] == 400
    assert error.failure["sdk_error"] == turn["error"]


def test_sdk_typed_outputschema_is_any_not_a_server_schema_validator():
    from openai_codex.client import V2TurnStartParams

    invalid_server_schema = {"type": "object", "properties": {"x": {"type": "number"}}}
    params = V2TurnStartParams.model_validate(
        {"threadId": "OFFLINE", "input": [], "outputSchema": invalid_server_schema}
    )
    assert params.output_schema == invalid_server_schema


@pytest.mark.parametrize(
    "model,payload,field",
    [
        (PlanSpec, RESEARCH, "recommendation"),
        (NumericSpec, TRADER, "action"),
        (DecisionSpec, PORTFOLIO, "rating"),
        (ScoreSpec, SENTIMENT, "overall_band"),
        (ScoreSpec, SENTIMENT, "confidence"),
    ],
)
def test_every_declared_enum_literal_value_survives_forward_inverse(model, payload, field):
    definition = model.model_json_schema()["properties"][field]
    values = definition.get("enum")
    if values is None:
        key = definition["$ref"].split("/")[-1]
        values = model.model_json_schema()["$defs"][key]["enum"]
    for value in values:
        encoded, _ = encode_business_value(model, {**payload, field: value})
        assert model.model_validate(encoded).model_dump(mode="json")[field] == value


@pytest.mark.parametrize(
    "exception,category",
    [
        (TimeoutError("OFFLINE"), "TRANSPORT_OR_TIMEOUT"),
        (
            CodexTurnError(
                {
                    "status": "failed",
                    "error": {
                        "message": json.dumps(
                            {"status": 400, "error": {"code": "invalid_json_schema"}}
                        )
                    },
                }
            ),
            "SERVER_SCHEMA_REJECTED",
        ),
    ],
)
def test_runtime_errors_are_not_mislabeled_as_pydantic_failure(exception, category, monkeypatch):
    def invoke(*args, **kwargs):
        raise exception

    monkeypatch.setattr(ChatCodexSDK, "invoke", invoke)
    model = ChatCodexSDK()
    with pytest.raises(type(exception)):
        model.with_structured_output(PlanSpec).invoke("OFFLINE")
    assert model.structured_evidence[0]["phase"] == "sdk_invocation"
    assert model.structured_evidence[0]["failure_category"] == category


def test_native_sdk_worker_preserves_server_error_and_unknown_usage(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from langchain_codex_sdk import tools as codex_tools
    from langchain_codex_sdk.usage import CodexResources

    failure = {
        "status": "failed",
        "error": {
            "message": json.dumps(
                {
                    "status": 400,
                    "error": {
                        "code": "invalid_json_schema",
                        "type": "invalid_request_error",
                        "param": "text.format.schema",
                    },
                }
            )
        },
    }

    class SDKMock:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def initialize(self):
            pass

        def close(self):
            pass

        def account_read(self, *args):
            return SimpleNamespace(model_dump=lambda **kwargs: {"account": {"type": "chatgpt"}})

        def thread_start(self, *args):
            return SimpleNamespace(thread=SimpleNamespace(id="OFFLINE_THREAD"), model="gpt-6.1-sol")

        def turn_start(self, *args):
            return SimpleNamespace(turn=SimpleNamespace(id="OFFLINE_TURN"))

        def next_turn_notification(self, *args):
            return SimpleNamespace(
                method="turn/completed",
                payload=SimpleNamespace(model_dump=lambda **kwargs: {"turn": failure}),
            )

    monkeypatch.setattr(codex_tools, "CodexClient", SDKMock)
    monkeypatch.setattr(codex_tools, "restricted_config", lambda *a: object())
    guard = CodexResources(tmp_path / "ledger.json", max_tasks=1, reserve_per_task=100)
    session = codex_tools.NativeToolSession(
        model="gpt-6.1-sol",
        instructions="",
        prompt="OFFLINE",
        cwd=str(tmp_path),
        codex_bin=None,
        timeout=2,
        tools=[],
        digest="OFFLINE",
        resource_guard=guard,
    )
    with pytest.raises(CodexTurnError) as caught:
        session.next_result()
    session.done.wait(2)
    assert caught.value.failure["service_error_code"] == "invalid_json_schema"
    assert caught.value.failure["sdk_error"] == failure["error"]
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert ledger["unknown_tasks"] == 1 and ledger["observed_total_tokens"] == 0
    assert ledger["sessions"][session.id]["usage"] is None
    assert ledger["actual_total_upper_bound"] is None


def test_annotated_ref_constraints_are_never_silently_merged():
    schema = {
        "type": "object",
        "$defs": {"N": {"type": "number", "minimum": 0}},
        "properties": {"x": {"$ref": "#/$defs/N", "minimum": 10}},
        "required": ["x"],
    }
    with pytest.raises(SchemaCompatibilityError, match="constrained/recursive"):
        normalize_output_schema(schema)

# SPDX-License-Identifier: Apache-2.0
# Extracted and modified from the TradingAgents Codex Adapter; see NOTICE.
"""Auditable canonical-value bridge to the official strict outputSchema.

Original Pydantic classes remain the business definition. Optional fields may
be promoted only when omission defaults to None and null is already allowed.
Arbitrary maps and other defaults are explicitly blocked, never approximated.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass

from jsonschema import Draft202012Validator


class SchemaCompatibilityError(ValueError):
    """No lossless canonical-value mapping has been established."""


@dataclass
class SchemaNormalization:
    original: dict
    wire: dict
    changes: list[dict]


def normalize_output_schema(schema: dict) -> SchemaNormalization:
    original = copy.deepcopy(schema)
    Draft202012Validator.check_schema(original)
    wire, changes = copy.deepcopy(original), []
    validator = Draft202012Validator(original)

    def local_refs_only(node):
        if isinstance(node, dict):
            for key in ["$ref", "$dynamicRef"]:
                if key in node and not node[key].startswith("#/"):
                    raise SchemaCompatibilityError("External/root recursive references are BLOCKED")
            for child in node.values():
                local_refs_only(child)
        elif isinstance(node, list):
            for child in node:
                local_refs_only(child)

    local_refs_only(original)

    def visit(node, path, ref_stack=()):
        if not isinstance(node, dict):
            return
        ref = node.get("$ref")
        if ref and not ref.startswith("#/"):
            raise SchemaCompatibilityError(f"{path}: external references are BLOCKED")
        if ref and len(node) > 1:
            annotations = {
                "description",
                "title",
                "default",
                "examples",
                "deprecated",
                "readOnly",
                "writeOnly",
            }
            siblings = set(node) - {"$ref"}
            if siblings - annotations or ref in ref_stack:
                raise SchemaCompatibilityError(
                    f"{path}: constrained/recursive annotated ref mapping is BLOCKED"
                )
            target = original
            try:
                for part in ref[2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError) as exc:
                raise SchemaCompatibilityError(f"{path}: unresolved local reference") from exc
            if not isinstance(target, dict):
                raise SchemaCompatibilityError(f"{path}: referenced schema is not an object")
            merged = copy.deepcopy(target)
            for key in siblings:
                if key == "description" and key in merged:
                    merged[key] = merged[key] + "\n\n" + node[key]
                else:
                    merged[key] = copy.deepcopy(node[key])
            node.clear()
            node.update(merged)
            ref_stack = (*ref_stack, ref)
            changes.append(
                {
                    "path": path,
                    "operation": "inline_annotated_local_ref",
                    "source_ref": ref,
                    "business_constraints": "Copied from original definition; no constrained sibling merging",
                }
            )
        if node.get("type") == "object" or "properties" in node:
            if node.get("additionalProperties", False) is not False:
                raise SchemaCompatibilityError(f"{path}: arbitrary maps are BLOCKED")
            properties = node.get("properties", {})
            required = node.get("required", [])
            if not set(required) <= set(properties):
                raise SchemaCompatibilityError(f"{path}: required names outside properties")
            for name, field in properties.items():
                if name in required:
                    continue
                if "default" not in field or field["default"] is not None:
                    raise SchemaCompatibilityError(
                        f"{path}.{name}: optional-field mapping requires default=None"
                    )
                if not validator.evolve(schema=field).is_valid(None):
                    raise SchemaCompatibilityError(
                        f"{path}.{name}: optional-field mapping must already permit null"
                    )
                changes.append(
                    {
                        "path": path + "." + name,
                        "operation": "require_nullable_default_none",
                        "missing_business_value": None,
                        "wire_missing_value": "REJECT",
                    }
                )
            if node.get("additionalProperties") is not False:
                changes.append({"path": path, "operation": "close_object"})
            node["additionalProperties"] = False
            node["required"] = list(properties)
        if "default" in node:
            changes.append(
                {
                    "path": path,
                    "operation": "remove_default_annotation",
                    "original_default": node.pop("default"),
                }
            )
        # Walk only schema locations, never a property-name/description map.
        for keyword in ["$defs", "definitions", "properties"]:
            for key, child in node.get(keyword, {}).items():
                visit(child, f"{path}/{keyword}/{key}", ref_stack)
        for keyword in ["items", "not", "if", "then", "else"]:
            if keyword in node:
                visit(node[keyword], f"{path}/{keyword}", ref_stack)
        for keyword in ["anyOf", "oneOf", "allOf", "prefixItems"]:
            for index, child in enumerate(node.get(keyword, [])):
                visit(child, f"{path}/{keyword}/{index}", ref_stack)

    visit(wire, "$")
    Draft202012Validator.check_schema(wire)
    return SchemaNormalization(original, wire, changes)


def value_changes(before, after, path="$") -> list[dict]:
    """Preserve a trace of Pydantic defaults/coercions, including lost values."""
    changes = []
    if isinstance(before, dict) and isinstance(after, dict):
        for key in before.keys() | after.keys():
            if key not in before or key not in after:
                changes.append(
                    {
                        "path": f"{path}.{key}",
                        "before_present": key in before,
                        "after_present": key in after,
                        "before": before.get(key),
                        "after": after.get(key),
                    }
                )
            else:
                changes.extend(value_changes(before[key], after[key], f"{path}.{key}"))
    elif before != after or type(before) is not type(after):
        changes.append(
            {
                "path": path,
                "before_present": True,
                "after_present": True,
                "before": before,
                "after": after,
            }
        )
    return changes


def validate_wire(value, wire):
    # Standard JSON disallows NaN/Infinity even when Python/Pydantic allows it.
    def finite(node):
        if isinstance(node, float) and not math.isfinite(node):
            raise SchemaCompatibilityError("Non-finite JSON numbers are BLOCKED")
        if isinstance(node, dict):
            for v in node.values():
                finite(v)
        elif isinstance(node, list):
            for v in node:
                finite(v)

    finite(value)
    Draft202012Validator(wire).validate(value)


def encode_business_value(model, value):
    """Local forward codec; expose defaults/validators, reject dropped keys.

    This does not fill missing fields in a model's native response. The inverse
    native path requires every wire field, then validates the original model.
    """
    mapping = normalize_output_schema(model.model_json_schema())
    parsed = model.model_validate(value)
    encoded = parsed.model_dump(mode="json")
    changes = value_changes(value, encoded)
    if any(not change["after_present"] for change in changes):
        raise SchemaCompatibilityError("Encoding would drop supplied fields; BLOCKED")
    validate_wire(encoded, mapping.wire)
    return encoded, changes


class CodexTurnError(RuntimeError):
    """Preserve the SDK's terminal failure instead of a generic no-output error."""

    def __init__(self, turn):
        self.failure = describe_turn_failure(turn)
        super().__init__((turn.get("error") or {}).get("message") or "Codex turn failed")


def describe_turn_failure(turn):
    error = copy.deepcopy(turn.get("error"))
    service = {}
    try:
        payload = json.loads((error or {}).get("message", ""))
        if isinstance(payload, dict):
            service = payload
    except (ValueError, TypeError):
        pass
    inner = service.get("error") or {}
    if not isinstance(inner, dict):
        inner = {}
    code = inner.get("code")
    category = "SDK_TURN_FAILURE"
    if code == "invalid_json_schema":
        category = "SERVER_SCHEMA_REJECTED"
    elif code in {"unsupported_response_format", "unsupported_json_schema"}:
        category = "STRUCTURED_MODE_UNSUPPORTED"
    elif code in {"context_length_exceeded", "invalid_thread", "thread_not_found"}:
        category = "CONTEXT_OR_THREAD_STATE"
    return {
        "phase": "sdk_turn_completed",
        "category": category,
        "terminal_status": turn.get("status"),
        "sdk_error": error,
        "http_status": service.get("status"),
        "service_error_type": inner.get("type"),
        "service_error_code": code,
        "service_error_param": inner.get("param"),
    }

# SPDX-License-Identifier: Apache-2.0
# Extracted and modified from the TradingAgents Codex Adapter; see NOTICE.
"""Text-only message serialization inspired by langchain-codex messages.ts.

Role-labelled history and fenced JSON parsing are translated design elements
from Euan Cowie's MIT implementation; see NOTICE and docs/PROVENANCE.md.
System instructions remain separate from untrusted conversation/tool content.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage


def text_content(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError("Codex minimal adapter supports text content only")
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            parts.append(block["text"])
        else:
            raise ValueError("Unsupported message content block; images/files are not exposed")
    return "\n".join(parts)


def serialize_messages(messages: list[BaseMessage]) -> tuple[str, str]:
    instructions, history = [], []
    for message in messages:
        text = text_content(message.content)
        if isinstance(message, SystemMessage):
            instructions.append(text)
            continue
        role = {"human": "Human", "ai": "Assistant", "tool": "Tool"}.get(message.type)
        if role is None:
            raise ValueError(f"Unsupported message type: {message.type}")
        entry = {"role": role, "content": text}
        if isinstance(message, AIMessage) and message.tool_calls:
            entry["tool_calls"] = message.tool_calls
        if isinstance(message, ToolMessage):
            entry["tool_call_id"] = message.tool_call_id
            entry["name"] = message.name
        history.append(entry)
    # A JSON container keeps role labels and data delimiters unambiguous.
    return "\n\n".join(instructions), json.dumps(history, ensure_ascii=False)


def parse_json(text: str):
    match = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text.strip(), re.IGNORECASE)
    return json.loads(match.group(1) if match else text)


def native_output_schema(schema: dict) -> dict:
    """Canonical strict schema; original business definition stays unchanged."""
    from .schema import normalize_output_schema

    return normalize_output_schema(schema).wire

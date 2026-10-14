# SPDX-License-Identifier: Apache-2.0
# Extracted and modified from the TradingAgents Codex Adapter; see NOTICE.
"""Minimal opt-in Codex BaseChatModel over the official Python SDK.

Design attribution: langchain-codex messages.ts / structured_output.ts (MIT);
Python interface references: open-langchain and DeerFlow, without their auth or
HTTP implementations. See NOTICE and docs/PROVENANCE.md.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import tempfile
import threading
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import BaseModel, Field, PrivateAttr

from .messages import parse_json, serialize_messages
from .schema import CodexTurnError, normalize_output_schema, validate_wire, value_changes


class ChatCodexSDK(BaseChatModel):
    model: str = Field(default="gpt-6.1-sol", min_length=1)
    working_directory: str = Field(
        default_factory=lambda: tempfile.mkdtemp(prefix="langchain-codex-")
    )
    codex_bin: str | None = None
    timeout_seconds: float = Field(default=120, gt=0)
    allowed_tools: tuple[str, ...] | None = None
    event_log_path: str | None = None
    allow_history_replay: bool = False
    resource_guard: Any = Field(default=None, exclude=True)
    task_key_prefix: str | None = None
    reservation_tokens: int | None = Field(default=None, ge=0)
    recovery_context: str | None = None
    _evidence: list[dict] = PrivateAttr(default_factory=list)
    _sessions: dict = PrivateAttr(default_factory=dict)
    _structured_evidence: list[dict] = PrivateAttr(default_factory=list)
    _failed_structured_prompts: set[str] = PrivateAttr(default_factory=set)
    _fallback_evidence: list[dict] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "langchain-codex-sdk-community"

    @property
    def _identifying_params(self) -> dict:
        return {"model": self.model, "provider": "codex", "auth": "managed-chatgpt"}

    @property
    def evidence(self) -> list[dict]:
        return list(self._evidence)

    @property
    def structured_evidence(self) -> list[dict]:
        return list(self._structured_evidence)

    @property
    def fallback_evidence(self) -> list[dict]:
        return list(self._fallback_evidence)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if stop:
            raise ValueError("Stop sequences are not implemented by this minimal Codex adapter")
        instructions, prompt = serialize_messages(messages)
        digest = hashlib.sha256((instructions + "\n" + prompt).encode()).hexdigest()
        if kwargs.get("codex_output_schema") is None and digest in self._failed_structured_prompts:
            self._fallback_evidence.append(
                {
                    "kind": "plain_after_structured_failure",
                    "status": "BLOCKED",
                    "prompt_sha256": digest,
                    "new_sdk_tasks": 0,
                }
            )
            raise RuntimeError("Free-text fallback after structured failure blocked before SDK")
        # All calls share the already-validated native session lifecycle, including
        # failures/UNKNOWN usage. No tools are executed by this provider itself.
        return self._generate_tools(
            messages,
            instructions,
            prompt,
            kwargs.get("codex_tools", []),
            kwargs.get("codex_output_schema"),
            kwargs.get("_cancel_scope"),
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        """Executor-backed async interface; the SDK transport remains synchronous."""
        scope = _CancellationScope()
        work = functools.partial(
            self._generate,
            messages,
            stop=stop,
            run_manager=run_manager.get_sync() if run_manager else None,
            _cancel_scope=scope,
            **kwargs,
        )
        future = asyncio.get_running_loop().run_in_executor(None, work)
        try:
            return await future
        except asyncio.CancelledError:
            await asyncio.shield(asyncio.to_thread(scope.cancel))
            raise

    def stream(self, *args, **kwargs):
        raise NotImplementedError("Token streaming is UNVERIFIED; use invoke/ainvoke")

    async def astream(self, *args, **kwargs):
        raise NotImplementedError("Token streaming is UNVERIFIED; use invoke/ainvoke")
        yield  # async iterator contract; no fabricated final-message streaming

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        from .tools import normalize_tools

        if tool_choice not in (None, "auto") or kwargs:
            raise ValueError("Minimal native adapter supports automatic tool choice only")
        return self.bind(codex_tools=normalize_tools(tools, self.allowed_tools))

    def _generate_tools(
        self, messages, instructions, prompt, tools, output_schema=None, cancel_scope=None
    ):
        from .tools import NativeToolSession, message_digest

        if self.resource_guard is not None:
            self.resource_guard.ensure_can_infer()

        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        reference = (
            last_ai.additional_kwargs.get("codex_native_session")
            if last_ai is not None and last_ai.tool_calls
            else None
        )
        if reference:
            session = self._sessions.get(reference)
            if session is None:
                if not self.allow_history_replay:
                    raise RuntimeError(
                        "Native session is unavailable; cold checkpoint resume is not implemented"
                    )
                from langchain_core.messages import ToolMessage

                last_ai_index = messages.index(last_ai)
                returned = [
                    m.tool_call_id
                    for m in messages[last_ai_index + 1 :]
                    if isinstance(m, ToolMessage)
                ]
                if len(returned) != len(set(returned)):
                    raise ValueError("Duplicate saved ToolMessage; recovery refused")
                if {c["id"] for c in last_ai.tool_calls} != set(returned):
                    raise ValueError("Explicit history replay requires the saved real tool results")
            elif session.tools != tools:
                raise ValueError("Bound tools differ from the pending session")
            else:
                session.reply(messages)
        else:
            session = None
        fresh_task = session is None
        if fresh_task:
            session = NativeToolSession(
                model=self.model,
                instructions=instructions,
                prompt=prompt,
                cwd=self.working_directory,
                codex_bin=self.codex_bin,
                timeout=self.timeout_seconds,
                tools=tools,
                digest=message_digest(messages),
                event_log_path=self.event_log_path,
                recovery_reference=reference or self.recovery_context,
                resource_guard=self.resource_guard,
                output_schema=output_schema,
                task_key=(
                    self.task_key_prefix
                    + ":"
                    + message_digest(messages)
                    + (
                        ":schema:"
                        + hashlib.sha256(
                            json.dumps(output_schema, sort_keys=True).encode()
                        ).hexdigest()
                        if output_schema is not None
                        else ""
                    )
                )
                if self.task_key_prefix
                else None,
                reservation_tokens=self.reservation_tokens,
            )
            self._sessions[session.id] = session
        if cancel_scope is not None:
            cancel_scope.add(session)
        session._record(
            "adapter/history_handling",
            {
                "message_count": len(messages),
                "history_bytes": len(prompt.encode()),
                "instructions_bytes": len(instructions.encode()),
                "full_history_sent": fresh_task,
                "path": "new_task" if fresh_task else "native_tool_result_only",
            },
        )
        try:
            kind, value = session.next_result()
        except Exception:
            self._evidence.append(session.snapshot())
            self._sessions.pop(session.id, None)
            raise
        snapshot = session.snapshot()
        self._evidence.append(snapshot)
        calls = [value] if kind == "tool" else []
        usage = snapshot["usage"] if kind == "final" else None
        metadata = (
            None
            if usage is None
            else {
                "input_tokens": usage["inputTokens"],
                "output_tokens": usage["outputTokens"],
                "total_tokens": usage["totalTokens"],
                "input_token_details": {"cache_read": usage.get("cachedInputTokens", 0)},
                "output_token_details": {"reasoning": usage.get("reasoningOutputTokens", 0)},
            }
        )
        message = AIMessage(
            content="" if kind == "tool" else value,
            tool_calls=calls,
            additional_kwargs={"codex_native_session": session.id},
            usage_metadata=metadata,
            response_metadata={
                **{
                    k: snapshot[k]
                    for k in ["thread_id", "turn_id", "model", "auth_kind", "tool_protocol"]
                },
                "codex_usage": usage,
                "usage_status": "MEASURED"
                if usage is not None
                else "PENDING"
                if calls
                else "UNKNOWN",
            },
        )
        if kind == "final":
            session.close()
            self._sessions.pop(session.id, None)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        for session in list(self._sessions.values()):
            session.close()
        self._sessions.clear()

    def cancel(self, reason="cancelled"):
        for session in list(self._sessions.values()):
            session.cancel(reason)
            self._evidence.append(session.snapshot())
        self._sessions.clear()

    def with_structured_output(self, schema, *, include_raw=False, **kwargs):
        if kwargs.get("method", "json_schema") != "json_schema":
            raise ValueError(
                "Codex structured output uses the official outputSchema interface only"
            )
        if set(kwargs) - {"method"}:
            raise ValueError("Unsupported structured-output options")
        is_pydantic = isinstance(schema, type) and issubclass(schema, BaseModel)
        output_schema = schema.model_json_schema() if is_pydantic else schema
        if not isinstance(output_schema, dict):
            raise TypeError("Expected a Pydantic model class or JSON Schema dictionary")
        try:
            mapping = normalize_output_schema(output_schema)
        except Exception as exc:
            self._structured_evidence.append(
                {
                    "schema": output_schema,
                    "status": "BLOCKED",
                    "phase": "schema_normalization",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "fallback": "NOT_USED",
                }
            )
            raise
        transport_schema = mapping.wire
        output_schema = mapping.original

        def invoke(value, config=None):
            event = {
                "schema": output_schema,
                "transport_schema": transport_schema,
                "normalization_changes": mapping.changes,
                "schema_type": f"{schema.__module__}.{schema.__name__}"
                if is_pydantic
                else "JSON Schema",
                "status": "ATTEMPTED",
                "phase": "sdk_invocation",
                "fallback": "NOT_USED",
            }
            instructions, prompt = serialize_messages(self._convert_input(value).to_messages())
            digest = hashlib.sha256((instructions + "\n" + prompt).encode()).hexdigest()
            try:
                raw = self.invoke(value, config=config, codex_output_schema=transport_schema)
                event.update(raw_text=raw.content, response_metadata=raw.response_metadata)
                event["phase"] = "json_parse"
                payload = parse_json(raw.content)
                event["raw_payload"] = payload
                event["phase"] = "pydantic_validation" if is_pydantic else "business_json_schema"
                if is_pydantic:
                    parsed = schema.model_validate(payload)
                    event["pydantic_value_changes"] = value_changes(
                        payload, parsed.model_dump(mode="json")
                    )
                else:
                    from jsonschema import validate

                    validate(payload, output_schema)
                    parsed = payload
                event["phase"] = "wire_response_validation"
                validate_wire(payload, transport_schema)
            except Exception as exc:
                event.update(status="FAIL", error_type=type(exc).__name__, error=str(exc))
                if isinstance(exc, CodexTurnError):
                    event["runtime_failure"] = exc.failure
                    event["failure_category"] = exc.failure["category"]
                elif isinstance(exc, TimeoutError) or "Transport" in type(exc).__name__:
                    event["failure_category"] = "TRANSPORT_OR_TIMEOUT"
                else:
                    event["failure_category"] = event["phase"].upper()
                self._failed_structured_prompts.add(digest)
                self._structured_evidence.append(event)
                raise
            event.update(
                status="PASS",
                phase="completed",
                parsed=parsed.model_dump(mode="json") if is_pydantic else parsed,
            )
            self._failed_structured_prompts.discard(digest)
            self._structured_evidence.append(event)
            # Deliberately no free-text fallback and no swallowed validation errors.
            return {"raw": raw, "parsed": parsed, "parsing_error": None} if include_raw else parsed

        return RunnableLambda(invoke)


class _CancellationScope:
    """Cancel only this asynchronous invocation, including the startup race."""

    def __init__(self):
        self.lock = threading.Lock()
        self.cancelled = False
        self.sessions = []

    def add(self, session):
        with self.lock:
            self.sessions.append(session)
            cancelled = self.cancelled
        if cancelled:
            session.cancel("async_cancelled")

    def cancel(self):
        with self.lock:
            self.cancelled = True
            sessions = list(self.sessions)
        for session in sessions:
            session.cancel("async_cancelled")

# SPDX-License-Identifier: Apache-2.0
# Extracted and modified from the TradingAgents Codex Adapter; see NOTICE.
"""M3 experimental native App Server request -> LangGraph -> native reply bridge.

Tool normalization/argument validation follows langchain-codex's MIT design.
The suspended official SDK callback and its result correlation are new code.
No tool is executed here: only the caller's LangGraph ToolNode executes it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import queue
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import validate
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai_codex.client import CodexClient

from .messages import serialize_messages
from .runtime import SECURITY_INSTRUCTIONS, deny_request, restricted_config
from .schema import CodexTurnError


def message_digest(messages) -> str:
    instructions, prompt = serialize_messages(messages)
    return hashlib.sha256((instructions + "\n" + prompt).encode()).hexdigest()


def normalize_tools(tools, allowed_names: tuple[str, ...] | None) -> list[dict]:
    specs = []
    for tool in tools:
        function = convert_to_openai_tool(tool)["function"]
        name = function["name"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("Invalid dynamic tool name")
        if allowed_names is not None and name not in allowed_names:
            raise ValueError(f"Tool is outside explicit allowlist: {name}")
        if name in {s["name"] for s in specs}:
            raise ValueError("Duplicate bound tool name")
        schema = copy.deepcopy(function["parameters"])
        schema["additionalProperties"] = False
        specs.append(
            {
                "type": "function",
                "name": name,
                "description": function.get("description", ""),
                "inputSchema": schema,
            }
        )
    return specs


class NativeToolSession:
    def __init__(
        self,
        *,
        model,
        instructions,
        prompt,
        cwd,
        codex_bin,
        timeout,
        tools,
        digest,
        event_log_path=None,
        recovery_reference=None,
        resource_guard=None,
        output_schema=None,
        task_key=None,
        reservation_tokens=None,
    ):
        self.id = str(uuid.uuid4())
        self.task_key = task_key
        self.reservation_tokens = reservation_tokens
        self.model = model
        self.tools = tools
        self.history_digest = digest
        self.timeout = timeout
        self.thread_id = None
        self.turn_id = None
        self.events = []
        self.usage = None
        self.terminal_status = None
        self.pending = None
        self.started = time.monotonic()
        self.outputs = queue.Queue()
        self.results = queue.Queue()
        self.closed = threading.Event()
        self.done = threading.Event()
        self.event_log_path = event_log_path
        self.journal_lock = threading.Lock()
        self.stop_reason = None
        self.cancel_lock = threading.Lock()
        self.cancel_requested = threading.Event()
        self.actual_model = None
        self.auth_kind = None
        self.resource_guard = resource_guard
        self._resource_settled = False
        self.output_schema = output_schema
        if resource_guard is not None:
            resource_guard.acquire(self)
        self._record(
            "adapter/input",
            {
                "instructions": instructions,
                "history": prompt,
                "tools": tools,
                "requested_model": model,
                "recovery_reference": recovery_reference,
                "recovery_mode": "new_task_history_replay" if recovery_reference else "fresh_task",
            },
        )
        try:
            self.client = CodexClient(
                restricted_config(cwd, codex_bin), approval_handler=self._request
            )
        except Exception:
            if resource_guard is not None:
                resource_guard.release(
                    self.id, terminal_observed=False, reason="client_creation_failed"
                )
            raise
        self.worker = threading.Thread(
            target=self._run, args=(instructions, prompt, cwd), daemon=True
        )
        self.worker.start()

    def _record(self, method, params):
        event = {
            "method": method,
            "params": copy.deepcopy(params),
            "timestamp_utc": datetime.now(UTC).isoformat(),
        }
        self.events.append(event)
        path = getattr(self, "event_log_path", None)
        if path:
            payload = {"session_id": self.id, **event}
            with self.journal_lock:
                target = Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    stream.flush()

    def _request(self, method, params):
        if method != "item/tool/call":
            return deny_request(method, params)
        if self.closed.is_set():
            return {
                "success": False,
                "contentItems": [{"type": "inputText", "text": "Session cancelled"}],
            }
        params = params or {}
        spec = next((t for t in self.tools if t["name"] == params.get("tool")), None)
        if spec is None or params.get("namespace") is not None:
            raise ValueError("Unregistered tool/namespace requested")
        args = params.get("arguments")
        validate(args, spec["inputSchema"])
        if not isinstance(params.get("callId"), str) or not params["callId"].strip():
            raise ValueError("Native tool request has no correlation ID")
        self._record(method, params)
        self.pending = {"name": spec["name"], "args": args, "id": params["callId"]}
        self.outputs.put(("tool", copy.deepcopy(self.pending)))
        try:
            result = self.results.get(timeout=self.timeout)
        except queue.Empty as exc:
            raise TimeoutError("Timed out awaiting LangGraph tool result") from exc
        if result is None:
            self._record("adapter/tool_cancelled", {"callId": params["callId"]})
            return {
                "success": False,
                "contentItems": [{"type": "inputText", "text": "Session cancelled"}],
            }
        self.pending = None
        return result

    def _run(self, instructions, prompt, cwd):
        answer = None
        try:
            if self.closed.is_set():
                raise RuntimeError("Codex session cancelled before startup")
            self.client.start()
            self.client.initialize()
            account = self.client.account_read({"refreshToken": False}).model_dump(
                by_alias=True, mode="json"
            )
            if (account.get("account") or {}).get("type") != "chatgpt":
                raise RuntimeError("ChatGPT-managed login required")
            self.auth_kind = "chatgpt"
            thread = self.client.thread_start(
                {
                    "cwd": cwd,
                    "model": self.model,
                    "modelProvider": "openai",
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "ephemeral": True,
                    "environments": [],
                    "dynamicTools": self.tools,
                    "baseInstructions": SECURITY_INSTRUCTIONS,
                    "developerInstructions": instructions,
                }
            )
            self.thread_id = thread.thread.id
            self.actual_model = thread.model
            if self.actual_model != self.model:
                raise RuntimeError("Runtime selected a different model; invocation stopped")
            self._record(
                "adapter/thread_started",
                {"thread_id": self.thread_id, "model": self.actual_model, "auth_kind": "chatgpt"},
            )
            turn_params = {"effort": "low", "environments": []}
            if self.output_schema is not None:
                turn_params["outputSchema"] = self.output_schema
            self._record("adapter/turn_parameters", turn_params)
            turn = self.client.turn_start(self.thread_id, prompt, turn_params)
            self.turn_id = turn.turn.id
            self._record(
                "adapter/turn_started", {"thread_id": self.thread_id, "turn_id": self.turn_id}
            )
            while not self.closed.is_set():
                event = self.client.next_turn_notification(self.turn_id)
                data = event.payload.model_dump(by_alias=True, mode="json")
                if event.method in {
                    "item/completed",
                    "thread/tokenUsage/updated",
                    "turn/completed",
                }:
                    self._record(event.method, data)
                if event.method == "model/rerouted":
                    self._record(event.method, data)
                    raise RuntimeError("Unexpected model rerouting; invocation stopped")
                if event.method == "thread/tokenUsage/updated":
                    self.usage = data.get("tokenUsage", {}).get("total")
                    if self.resource_guard is not None:
                        self.resource_guard.observe(
                            self.id, self.usage, raw_usage=data.get("tokenUsage")
                        )
                if event.method == "item/completed":
                    item = data.get("item", {})
                    if item.get("type") == "agentMessage" and item.get("phase") in (
                        None,
                        "final_answer",
                    ):
                        answer = item.get("text")
                    elif item.get("type") not in {
                        "agentMessage",
                        "userMessage",
                        "reasoning",
                        "dynamicToolCall",
                    }:
                        raise RuntimeError("Unexpected built-in action; native invocation aborted")
                if event.method == "turn/completed":
                    self.terminal_status = data["turn"]["status"]
                    if data["turn"]["status"] != "completed" and data["turn"].get("error"):
                        raise CodexTurnError(data["turn"])
                    if data["turn"]["status"] != "completed" or answer is None:
                        raise RuntimeError(
                            "Native tool turn did not produce a completed final response"
                        )
                    # A short-lived caller can exit immediately after receiving
                    # this result. Settle durable usage before publishing it;
                    # SDK process shutdown may block in client.close().
                    self._settle_resource()
                    self.outputs.put(("final", answer))
                    break
        except Exception as exc:
            self._record(
                "adapter/error", {"type": type(exc).__name__, "stop_reason": self.stop_reason}
            )
            self._settle_resource()
            self.outputs.put(("error", exc))
        finally:
            try:
                self._settle_resource()
                self.client.close()
            finally:
                self.done.set()

    def _settle_resource(self):
        if self.resource_guard is not None and not self._resource_settled:
            self.resource_guard.release(
                self.id,
                terminal_observed=self.terminal_status is not None,
                reason=self.stop_reason or "transport_or_inference_error",
            )
            self._resource_settled = True

    def next_result(self):
        try:
            kind, value = self.outputs.get(timeout=self.timeout)
        except queue.Empty as exc:
            self.cancel("timeout")
            raise TimeoutError("Native Codex invocation timed out") from exc
        if kind == "error":
            self.close()
            raise value
        return kind, value

    def reply(self, messages):
        if self.pending is None:
            raise ValueError("There is no suspended native tool request")
        last_ai = next(
            (
                i
                for i in range(len(messages) - 1, -1, -1)
                if isinstance(messages[i], AIMessage) and messages[i].tool_calls
            ),
            None,
        )
        if last_ai is None or message_digest(messages[:last_ai]) != self.history_digest:
            raise ValueError("Tool result history does not match the isolated pending session")
        results = [m for m in messages[last_ai + 1 :] if isinstance(m, ToolMessage)]
        if len(results) != 1 or results[0].tool_call_id != self.pending["id"]:
            raise ValueError("Tool result must match the single native correlation ID")
        result = results[0]
        if result.name != self.pending["name"] or not isinstance(result.content, str):
            raise ValueError("Tool result name/content does not match the suspended request")
        self._record(
            "client/tool_result",
            {
                "callId": result.tool_call_id,
                "tool": result.name,
                "text": result.content,
                "status": result.status,
            },
        )
        self.history_digest = message_digest(messages)
        self.results.put(
            {
                "success": result.status != "error",
                "contentItems": [{"type": "inputText", "text": result.content}],
            }
        )

    def snapshot(self):
        return copy.deepcopy(
            {
                "session_id": self.id,
                "thread_id": self.thread_id,
                "turn_id": self.turn_id,
                "model": self.model,
                "actual_model": getattr(self, "actual_model", None),
                "auth_kind": self.auth_kind,
                "usage": self.usage,
                "events": self.events,
                "elapsed_seconds": round(time.monotonic() - self.started, 3),
                "tool_protocol": "app-server-dynamic-experimental",
            }
        )

    def close(self):
        self.closed.set()
        self.results.put(None)
        self.client.close()

    def cancel(self, reason="cancelled"):
        with self.cancel_lock:
            if self.done.is_set():
                self.close()
                return
            if self.cancel_requested.is_set():
                return
            self.cancel_requested.set()
        self.stop_reason = reason
        self._record("adapter/cancel_requested", {"reason": reason})
        # Unblock the SDK reader callback before sending turn/interrupt on it.
        self.results.put(None)
        acknowledged = threading.Event()

        def interrupt():
            try:
                if self.thread_id and self.turn_id:
                    self.client.turn_interrupt(self.thread_id, self.turn_id)
                    self._record("adapter/interrupt_acknowledged", {"turn_id": self.turn_id})
                acknowledged.set()
            except Exception as exc:
                self._record("adapter/interrupt_error", {"type": type(exc).__name__})
                acknowledged.set()

        threading.Thread(target=interrupt, daemon=True).start()
        acknowledged.wait(3)
        self.done.wait(2)
        self.close()

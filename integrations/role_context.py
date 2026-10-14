# SPDX-License-Identifier: Apache-2.0
# Extracted from original Codex graph provider integration; see NOTICE.
"""Role-local Codex contexts for the unchanged official full graph.

LangGraph runnable metadata selects a model; no financial prompts, tools, nodes
or routes are replaced. Live pending tool continuations remain in their role's
model. A new process explicitly replays saved messages into a new SDK thread.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.runnables.config import ensure_config

from langchain_codex_sdk import ChatCodexSDK
from langchain_codex_sdk.recovery import write_json

ROLES = (
    "Market Analyst",
    "Fundamentals Analyst",
    "Bull Researcher",
    "Bear Researcher",
    "Research Manager",
    "Trader",
    "Aggressive Analyst",
    "Conservative Analyst",
    "Neutral Analyst",
    "Portfolio Manager",
)


def graph_role(config=None):
    metadata = ensure_config(config).get("metadata", {})
    namespace = metadata.get("langgraph_checkpoint_ns", "")
    for role in ROLES:
        if namespace.startswith(role + ":") or metadata.get("langgraph_node") == role:
            return role
    raise ValueError(f"Unknown official graph model context: {metadata.get('langgraph_node')}")


class NodeFailures:
    """Persist failures of graph attempts, not duplicate fallback callbacks."""

    def __init__(self, path):
        self.path = Path(path)
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}

    def failed(self, roles):
        for role in set(roles):
            self.state[role] = self.state.get(role, 0) + 1
        write_json(self.path, self.state)

    def completed(self, role):
        self.state[role] = 0
        write_json(self.path, self.state)

    def check(self):
        bad = [role for role, streak in self.state.items() if streak >= 3]
        if bad:
            raise RuntimeError(f"Three consecutive node failures; diagnosis required: {bad}")


class CodexGraphModel(Runnable):
    def __init__(
        self,
        *,
        directory,
        guard,
        attempt,
        allowed_tools,
        resume=False,
        model_factory=ChatCodexSDK,
    ):
        self.directory = Path(directory)
        self.guard, self.attempt = guard, attempt
        self.allowed_tools, self.resume = allowed_tools, resume
        self.model_factory = model_factory
        self.models = {}
        self.lock = threading.Lock()

    def model_for(self, config=None):
        role = graph_role(config)
        with self.lock:
            if role not in self.models:
                slug = role.lower().replace(" ", "_")
                self.models[role] = self.model_factory(
                    model="gpt-6.1-sol",
                    working_directory=str(self.directory / "runtime" / slug),
                    allowed_tools=self.allowed_tools,
                    event_log_path=str(self.directory / f"{slug}_runtime.jsonl"),
                    resource_guard=self.guard,
                    timeout_seconds=180,
                    allow_history_replay=self.resume,
                    task_key_prefix=f"integration:{self.attempt}:{role}",
                    recovery_context="CHECKPOINT_NEW_THREAD_REPLAY" if self.resume else None,
                )
            return self.models[role]

    def invoke(self, input, config=None, **kwargs):
        return self.model_for(config).invoke(input, config=config, **kwargs)

    def bind_tools(self, tools, **kwargs):
        def invoke(value, config=None):
            return self.model_for(config).bind_tools(tools, **kwargs).invoke(value, config=config)

        return RunnableLambda(invoke)

    def with_structured_output(self, schema, **kwargs):
        def invoke(value, config=None):
            return (
                self.model_for(config)
                .with_structured_output(schema, **kwargs)
                .invoke(value, config=config)
            )

        return RunnableLambda(invoke)

    def save(self):
        for role, model in self.models.items():
            slug = role.lower().replace(" ", "_")
            for name, value in [
                ("adapter", model.evidence),
                ("structured", model.structured_evidence),
                ("fallback", model.fallback_evidence),
            ]:
                write_json(self.directory / f"{slug}_{name}.json", value)

    def close(self):
        for model in self.models.values():
            model.close()
        self.save()

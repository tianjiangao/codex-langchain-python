# SPDX-License-Identifier: Apache-2.0
# Extracted and modified from the TradingAgents Codex Adapter; see NOTICE.
"""Local recovery seals and submission lock; no credentials or model calls.

A committed checkpoint is a replay boundary. Corruption, duplicate tool replies
and an ambiguous in-flight job stop recovery; they never reset it to the start.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage, messages_from_dict


class RecoveryIntegrityError(RuntimeError):
    pass


class DuplicateRecoverySubmission(RuntimeError):
    pass


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_saved_history(messages):
    calls, returned = {}, set()
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                if call["id"] in calls:
                    raise RecoveryIntegrityError("Duplicate saved tool-call ID")
                calls[call["id"]] = call["name"]
        if isinstance(message, ToolMessage):
            if message.tool_call_id in returned:
                raise RecoveryIntegrityError("Duplicate saved ToolMessage")
            if calls.get(message.tool_call_id) != message.name:
                raise RecoveryIntegrityError("ToolMessage has foreign ID/name")
            returned.add(message.tool_call_id)
    if set(calls) != returned:
        raise RecoveryIntegrityError("Checkpoint has an unresolved tool result")


class RecoveryStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def lock(self):
        with (self.directory / "submission.lock").open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise DuplicateRecoverySubmission("Another process owns this recovery job") from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def job(self):
        path = self.directory / "job_state.json"
        return json.loads(path.read_text()) if path.exists() else None

    def transition(self, status, **metadata):
        old = self.job() or {}
        write_json(self.directory / "job_state.json", {**old, **metadata, "status": status})

    def seal(self, connection, state, metadata):
        validate_saved_history(messages_from_dict(state["values"]["messages"]))
        path = self.directory / "checkpoint.sqlite"
        temp = path.with_suffix(".tmp")
        with sqlite3.connect(temp) as target:
            connection.backup(target)
        temp.replace(path)
        write_json(self.directory / "graph_state_before.json", state)
        write_json(
            self.directory / "checkpoint_manifest.json",
            {
                "version": 1,
                "state_sha256": file_sha256(self.directory / "graph_state_before.json"),
                "sqlite_sha256": file_sha256(path),
                **metadata,
            },
        )

    def verify(self):
        try:
            manifest = json.loads((self.directory / "checkpoint_manifest.json").read_text())
            for name, key in [
                ("graph_state_before.json", "state_sha256"),
                ("checkpoint.sqlite", "sqlite_sha256"),
            ]:
                if file_sha256(self.directory / name) != manifest[key]:
                    raise RecoveryIntegrityError(f"Corrupt checkpoint: {name}")
            state = json.loads((self.directory / "graph_state_before.json").read_text())
            validate_saved_history(messages_from_dict(state["values"]["messages"]))
            with sqlite3.connect(
                f"file:{self.directory / 'checkpoint.sqlite'}?mode=ro", uri=True
            ) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RecoveryIntegrityError("SQLite integrity check failed")
            return state, manifest
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            raise RecoveryIntegrityError(
                "Unreadable recovery checkpoint; no restart permitted"
            ) from exc

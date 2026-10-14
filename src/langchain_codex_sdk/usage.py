# SPDX-License-Identifier: Apache-2.0
# Extracted and modified from the TradingAgents Codex Adapter; see NOTICE.
"""Durable actual/UNKNOWN usage and conditional planning-budget ledger.

Cached tokens are part of input. Planning estimates are never an actual bill
or a proved server-side upper bound. Defaults retain strict UNKNOWN blocking;
explicit documented estimates allow bounded further task admissions.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
import threading
from pathlib import Path


class CodexResourceLimit(RuntimeError):
    pass


class DuplicateCodexTask(CodexResourceLimit):
    pass


class CodexResources:
    def __init__(
        self,
        path,
        *,
        max_active=2,
        token_limit=250_000,
        max_tasks=None,
        reserve_per_task=0,
        unknown_estimates=None,
        warning_fraction=0.8,
        process_lock=False,
        measured_only=False,
        soft_warning_tokens=None,
    ):
        self.path = Path(path)
        self._lease = None
        if process_lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._lease = self.path.with_suffix(".lock").open("a")
            try:
                fcntl.flock(self._lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                self._lease.close()
                raise CodexResourceLimit("Another process owns this usage ledger") from exc
        self.max_active, self.token_limit = max_active, token_limit
        self.max_tasks, self.reserve_per_task = max_tasks, reserve_per_task
        self.warning_fraction = warning_fraction
        self.measured_only = measured_only
        self.soft_warning_tokens = soft_warning_tokens
        if measured_only and (max_tasks is not None or reserve_per_task):
            raise ValueError("Measured-only policy has no task cap or admission reservations")
        self.lock = threading.RLock()
        self.active, self.sessions = {}, {}
        self.peak_active = 0
        self.warnings = []
        if self.path.exists():
            saved = json.loads(self.path.read_text())
            if saved.get("version") == 2:
                # A resumed caller cannot silently loosen resource policy.
                policy = saved["policy"]
                if (measured_only, soft_warning_tokens) != (
                    policy.get("measured_only", False),
                    policy.get("soft_warning_tokens"),
                ):
                    raise CodexResourceLimit(
                        "Persisted measurement policy differs; explicit migration required"
                    )
                if (token_limit, max_active, max_tasks, reserve_per_task) != (
                    policy["token_limit"],
                    policy["max_active"],
                    policy["max_tasks"],
                    policy["reserve_per_task"],
                ):
                    raise CodexResourceLimit(
                        "Persisted resource policy differs; explicit migration required"
                    )
            self.sessions = saved["sessions"]
            self.peak_active = saved["peak_active"]
            self.warnings = saved.get("warnings", [])
            for record in self.sessions.values():
                record.setdefault("reservation_tokens", 0)
                record.setdefault("task_key", None)
                record.setdefault("usage_events", [])
                if record["status"] == "active" or "usage_unverified" in record["status"]:
                    record.update(
                        status="process_interrupted_usage_unverified",
                        usage_status="UNKNOWN",
                        unknown_reason="process_restart_before_terminal_observation",
                    )
                    reservation = record.get("reservation_tokens", 0)
                    observed = (record.get("usage") or {}).get("totalTokens", 0)
                    if reservation and not record.get("estimate"):
                        record["estimate"] = {
                            "lower_tokens": observed,
                            "upper_tokens": max(observed, reservation),
                            "assumptions": "Process lost; missing tail conditionally held within the pre-admitted reservation. No proved SDK output ceiling.",
                            "classification": "CONDITIONAL_ESTIMATE",
                            "actual_upper_bound_proven": False,
                        }
                else:
                    record.setdefault(
                        "usage_status", "MEASURED" if record.get("usage") else "UNKNOWN"
                    )
        for sid, estimate in (unknown_estimates or {}).items():
            self.estimate_unknown(sid, **estimate)

    def _total(self):
        return sum((r.get("usage") or {}).get("totalTokens", 0) for r in self.sessions.values())

    def _charge(self, record):
        actual = (record.get("usage") or {}).get("totalTokens", 0)
        if record["status"] == "active":
            return max(actual, record.get("reservation_tokens", 0))
        if record.get("usage_status") == "UNKNOWN":
            return max(actual, (record.get("estimate") or {}).get("upper_tokens", 0))
        return actual

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        with temp.open("w") as stream:
            json.dump(self.snapshot(), stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)

    def snapshot(self):
        with self.lock:
            measured = [r.get("usage") or {} for r in self.sessions.values()]
            unknown = any(r.get("usage_status") == "UNKNOWN" for r in self.sessions.values())
            return {
                "version": 2,
                "policy": {
                    "token_limit": self.token_limit,
                    "max_active": self.max_active,
                    "max_tasks": self.max_tasks,
                    "reserve_per_task": self.reserve_per_task,
                    **(
                        {"measured_only": True, "soft_warning_tokens": self.soft_warning_tokens}
                        if self.measured_only
                        else {}
                    ),
                },
                "token_limit": self.token_limit,
                "max_active": self.max_active,
                "peak_active": self.peak_active,
                "active": list(self.active),
                "tasks_admitted": len(self.sessions),
                "observed_total_tokens": self._total(),
                "reported_breakdown": {
                    "input": sum(u.get("inputTokens", 0) for u in measured),
                    "output": sum(u.get("outputTokens", 0) for u in measured),
                    "cached_input_subset": sum(u.get("cachedInputTokens", 0) for u in measured),
                    "total": self._total(),
                },
                "actual_total_lower_bound": self._total(),
                "actual_total_upper_bound": None if unknown or self.active else self._total(),
                "planning_charge_tokens": sum(self._charge(r) for r in self.sessions.values()),
                "planning_upper_is_conditional": True,
                "unknown_tasks": sum(
                    r.get("usage_status") == "UNKNOWN" for r in self.sessions.values()
                ),
                "warnings": list(self.warnings),
                "sessions": copy.deepcopy(self.sessions),
            }

    def estimate_unknown(self, session_id, *, lower_tokens, upper_tokens, assumptions):
        with self.lock:
            record = self.sessions[session_id]
            observed = (record.get("usage") or {}).get("totalTokens", 0)
            if record.get("usage_status") != "UNKNOWN":
                raise ValueError("Estimates apply only to UNKNOWN usage")
            if lower_tokens < observed or upper_tokens < lower_tokens or not assumptions.strip():
                raise ValueError("Estimate must bound observed usage and document assumptions")
            record["estimate"] = {
                "lower_tokens": lower_tokens,
                "upper_tokens": upper_tokens,
                "assumptions": assumptions,
                "classification": "CONDITIONAL_ESTIMATE",
                "actual_upper_bound_proven": False,
            }
            self._save()

    def ensure_can_infer(self):
        with self.lock:
            if self._total() >= self.token_limit:
                raise CodexResourceLimit("Cumulative reported token limit reached")
            if self.measured_only:
                return  # UNKNOWN stays unknown; it does not bar healthy measured-only runs.
            if any(
                r.get("usage_status") == "UNKNOWN" and not r.get("estimate")
                for r in self.sessions.values()
            ):
                raise CodexResourceLimit(
                    "Prior task token usage is UNVERIFIED/UNKNOWN without an estimate"
                )
            if sum(self._charge(r) for r in self.sessions.values()) >= self.token_limit:
                raise CodexResourceLimit("Conditional planning budget exhausted")

    def acquire(self, session):
        with self.lock:
            self.ensure_can_infer()
            if len(self.active) >= self.max_active:
                raise CodexResourceLimit("Concurrent native session limit reached")
            if self.max_tasks is not None and len(self.sessions) >= self.max_tasks:
                raise CodexResourceLimit("Model task count limit reached")
            task_key = getattr(session, "task_key", None)
            if task_key and any(r.get("task_key") == task_key for r in self.sessions.values()):
                raise DuplicateCodexTask(
                    "Duplicate model task submission blocked; inspect prior state"
                )
            reservation = getattr(session, "reservation_tokens", None)
            reservation = self.reserve_per_task if reservation is None else reservation
            if reservation < 0:
                raise ValueError("Negative reservation")
            if not self.measured_only and (
                sum(self._charge(r) for r in self.sessions.values()) + reservation
                > self.token_limit
            ):
                raise CodexResourceLimit("Insufficient budget to reserve the next model task")
            self.active[session.id] = session
            self.sessions[session.id] = {
                "status": "active",
                "usage_status": "PENDING",
                "usage": None,
                "usage_events": [],
                "reservation_tokens": reservation,
                "task_key": task_key,
            }
            self.peak_active = max(self.peak_active, len(self.active))
            self._save()

    def observe(self, session_id, usage, *, raw_usage=None):
        with self.lock:
            record = self.sessions[session_id]
            if raw_usage is not None:
                record.setdefault("raw_sdk_usage", []).append(copy.deepcopy(raw_usage))
            if usage is not None:
                # Keep every original SDK total snapshot, including repeats.
                record["usage_events"].append(copy.deepcopy(usage))
                old = (record.get("usage") or {}).get("totalTokens", 0)
                if usage["totalTokens"] >= old:
                    record["usage"] = copy.deepcopy(usage)
            charge = sum(self._charge(r) for r in self.sessions.values())
            warning_value = self._total() if self.measured_only else charge
            warning_threshold = (
                self.soft_warning_tokens
                if self.soft_warning_tokens is not None
                else self.token_limit * self.warning_fraction
            )
            warning_label = "measured_soft_warning" if self.measured_only else "budget_warning"
            if warning_value >= warning_threshold and warning_label not in self.warnings:
                self.warnings.append(warning_label)
            observed = (record.get("usage") or {}).get("totalTokens", 0)
            reservation = record.get("reservation_tokens", 0)
            over_reservation = bool(reservation and observed > reservation)
            if over_reservation and f"reservation_exceeded:{session_id}" not in self.warnings:
                self.warnings.append(f"reservation_exceeded:{session_id}")
            self._save()
            over = self._total() >= self.token_limit or (
                not self.measured_only and (charge > self.token_limit or over_reservation)
            )
        if over:
            threading.Thread(target=self.cancel_all, args=("budget_exceeded",), daemon=True).start()

    def release(self, session_id, *, terminal_observed=True, reason=None):
        with self.lock:
            self.active.pop(session_id, None)
            record = self.sessions[session_id]
            record["status"] = "closed"
            record["usage_status"] = (
                "MEASURED" if terminal_observed and record.get("usage") is not None else "UNKNOWN"
            )
            if record["usage_status"] == "UNKNOWN":
                record["unknown_reason"] = reason or "usage_missing_at_terminal"
                # Reservation is an explicitly conditional estimate, not an invoice.
                reservation = record.get("reservation_tokens", 0)
                observed = (record.get("usage") or {}).get("totalTokens", 0)
                if reservation and "estimate" not in record:
                    record["estimate"] = {
                        "lower_tokens": observed,
                        "upper_tokens": max(observed, reservation),
                        "assumptions": "Task admitted under this reservation; missing tail estimated within reservation. No proved SDK output ceiling.",
                        "classification": "CONDITIONAL_ESTIMATE",
                        "actual_upper_bound_proven": False,
                    }
            self._save()

    def cancel_all(self, reason):
        with self.lock:
            sessions = list(self.active.values())
        workers = [threading.Thread(target=s.cancel, args=(reason,), daemon=True) for s in sessions]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=6)

    def close(self):
        if self.active:
            raise CodexResourceLimit("Cannot release ledger ownership with active tasks")
        if self._lease is not None:
            fcntl.flock(self._lease, fcntl.LOCK_UN)
            self._lease.close()
            self._lease = None

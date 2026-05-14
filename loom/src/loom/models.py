"""Shared models for Loom monitor state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class Signal(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    AUTH = "auth"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    OVERLOAD = "overload"
    COOLDOWN = "cooldown"
    TIMEOUT = "timeout"
    MISSING_BINARY = "missing_binary"


@dataclass(frozen=True)
class Provider:
    key: str
    display_name: str
    binary: str
    probe_args: tuple[str, ...]
    daily_budget: int
    hourly_budget: int
    timeout_seconds: int = 20


@dataclass
class UsageEvent:
    agent: str
    task: str
    command: list[str]
    started_at: str
    ended_at: str
    duration_ms: int
    exit_code: int | None
    signal: str
    prompt_tokens: int
    output_tokens: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "task": self.task,
            "command": self.command,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "signal": self.signal,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "stdout_excerpt": self.stdout_excerpt,
            "stderr_excerpt": self.stderr_excerpt,
            "reason": self.reason,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "UsageEvent":
        return cls(
            agent=str(payload["agent"]),
            task=str(payload.get("task", "")),
            command=list(payload.get("command", [])),
            started_at=str(payload["started_at"]),
            ended_at=str(payload["ended_at"]),
            duration_ms=int(payload.get("duration_ms", 0)),
            exit_code=payload.get("exit_code"),
            signal=str(payload.get("signal", Signal.FAILURE.value)),
            prompt_tokens=int(payload.get("prompt_tokens", 0)),
            output_tokens=int(payload.get("output_tokens", 0)),
            stdout_excerpt=str(payload.get("stdout_excerpt", "")),
            stderr_excerpt=str(payload.get("stderr_excerpt", "")),
            reason=str(payload.get("reason", "")),
        )


@dataclass
class AgentState:
    agent: str
    available: bool
    score: float
    reason: str
    calls_today: int
    calls_hour: int
    last_call_at: str | None = None
    cooldown_until: str | None = None
    active_tasks: int = 0
    failures_recent: int = 0
    risk_score: float = 0.0
    signals: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "available": self.available,
            "score": self.score,
            "reason": self.reason,
            "calls_today": self.calls_today,
            "calls_hour": self.calls_hour,
            "last_call_at": self.last_call_at,
            "cooldown_until": self.cooldown_until,
            "active_tasks": self.active_tasks,
            "failures_recent": self.failures_recent,
            "risk_score": self.risk_score,
            "signals": self.signals,
        }


@dataclass
class TaskSession:
    task_id: str
    session_name: str
    agent: str
    task: str
    repo: str
    status: str
    command: list[str]
    packet_path: str
    created_at: str
    updated_at: str
    routing_reason: str = ""
    routing_score: float = 0.0
    runtime: str = "tmux"
    runtime_pid: int | None = None
    log_path: str | None = None
    risk: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "session_name": self.session_name,
            "agent": self.agent,
            "task": self.task,
            "repo": self.repo,
            "status": self.status,
            "command": self.command,
            "packet_path": self.packet_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "routing_reason": self.routing_reason,
            "routing_score": self.routing_score,
            "runtime": self.runtime,
            "runtime_pid": self.runtime_pid,
            "log_path": self.log_path,
            "risk": self.risk,
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "TaskSession":
        return cls(
            task_id=str(payload["task_id"]),
            session_name=str(payload["session_name"]),
            agent=str(payload["agent"]),
            task=str(payload["task"]),
            repo=str(payload["repo"]),
            status=str(payload.get("status", "unknown")),
            command=list(payload.get("command", [])),
            packet_path=str(payload["packet_path"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            routing_reason=str(payload.get("routing_reason", "")),
            routing_score=float(payload.get("routing_score", 0.0)),
            runtime=str(payload.get("runtime", "tmux")),
            runtime_pid=payload.get("runtime_pid"),
            log_path=payload.get("log_path"),
            risk=str(payload.get("risk", "")),
        )


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)

"""Runtime backends for Loom task sessions."""

from __future__ import annotations

import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from loom.models import TaskSession, iso_now
from loom.providers import PROVIDERS, provider_command
from loom.scoring import aggregate_states, select_agent
from loom.storage import LoomStore

AGENT_ALIASES = {
    "codex": "codex_cli",
    "claude": "claude_cli",
    "gemini": "gemini_cli",
    "codex_cli": "codex_cli",
    "claude_cli": "claude_cli",
    "gemini_cli": "gemini_cli",
}


@dataclass(frozen=True)
class SpawnResult:
    session: TaskSession
    command: list[str]


class RuntimeErrorDetail(RuntimeError):
    """Raised when a runtime backend cannot complete an operation."""


class TmuxRuntime:
    name = "tmux"

    def available(self) -> bool:
        return shutil.which("tmux") is not None

    def spawn(self, session: TaskSession) -> None:
        if not self.available():
            raise RuntimeErrorDetail("tmux binary not found")
        command = _shell_join(session.command)
        tmux_name = _tmux_target(session.session_name)
        try:
            subprocess.run(
                [
                    "tmux",
                    "new-session",
                    "-d",
                    "-s",
                    tmux_name,
                    "-c",
                    session.repo,
                    command,
                ],
                check=True,
                text=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeErrorDetail(_tmux_error("spawn", exc)) from exc

    def attach(self, session_name: str) -> None:
        if not self.available():
            raise RuntimeErrorDetail("tmux binary not found")
        result = subprocess.run(["tmux", "attach-session", "-t", _tmux_target(session_name)], check=False)
        if result.returncode != 0:
            raise RuntimeErrorDetail(f"tmux attach failed for {session_name}")

    def stop(self, session_name: str) -> None:
        if not self.available():
            raise RuntimeErrorDetail("tmux binary not found")
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", _tmux_target(session_name)],
                check=True,
                text=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeErrorDetail(_tmux_error("stop", exc)) from exc


class FakeRuntime:
    name = "fake"

    def __init__(self) -> None:
        self.spawned: list[TaskSession] = []
        self.stopped: list[str] = []
        self.attached: list[str] = []

    def available(self) -> bool:
        return True

    def spawn(self, session: TaskSession) -> None:
        self.spawned.append(session)

    def attach(self, session_name: str) -> None:
        self.attached.append(session_name)

    def stop(self, session_name: str) -> None:
        self.stopped.append(session_name)


class LocalRuntime:
    name = "local"

    def __init__(self, store: LoomStore) -> None:
        self.store = store

    def available(self) -> bool:
        return True

    def spawn(self, session: TaskSession) -> None:
        self.store.ensure()
        log_path = self.store.log_dir / "tasks" / f"{session.task_id}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handle = log_path.open("ab")
        try:
            process = subprocess.Popen(  # noqa: S603
                session.command,
                cwd=session.repo,
                stdout=handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            session.runtime_pid = process.pid
            session.log_path = str(log_path)
        finally:
            handle.close()

    def attach(self, session_name: str) -> None:
        raise RuntimeErrorDetail(f"local runtime cannot attach to {session_name}; read its log instead")

    def stop(self, session_name: str) -> None:
        raise RuntimeErrorDetail(f"local runtime cannot stop {session_name} without session metadata")


def resolve_agent(value: str) -> str:
    try:
        return AGENT_ALIASES[value]
    except KeyError as exc:
        choices = ", ".join(sorted(AGENT_ALIASES))
        raise ValueError(f"unknown agent '{value}', expected one of: {choices}") from exc


def route_agent(store: LoomStore) -> tuple[str, str, float]:
    states = aggregate_states(store.read_events(), active_tasks=store.active_task_counts())
    selected = select_agent(states)
    store.write_state(states, selected.agent if selected else None)
    if selected is None:
        raise RuntimeErrorDetail("no providers configured")
    return selected.agent, selected.reason, selected.score


def spawn_task(
    store: LoomStore,
    task: str,
    *,
    agent: str | None = None,
    repo: Path | None = None,
    runtime: TmuxRuntime | FakeRuntime | None = None,
) -> SpawnResult:
    agent_key, reason, score = (
        (resolve_agent(agent), "manual agent override", 100.0) if agent else route_agent(store)
    )
    if runtime is None:
        tmux = TmuxRuntime()
        runtime = tmux if tmux.available() else LocalRuntime(store)
    repo_path = str((repo or Path.cwd()).resolve())
    task_id = uuid.uuid4().hex[:8]
    project = _slug(Path(repo_path).name or "repo")
    session_name = f"loom:{project}:{task_id}"
    packet = build_task_packet(task=task, repo=repo_path, agent=agent_key)
    packet_path = store.write_task_packet(task_id, packet)
    command = provider_command(PROVIDERS[agent_key], packet)
    now = iso_now()
    session = TaskSession(
        task_id=task_id,
        session_name=session_name,
        agent=agent_key,
        task=task,
        repo=repo_path,
        status="starting",
        command=command,
        packet_path=str(packet_path),
        created_at=now,
        updated_at=now,
        routing_reason=reason,
        routing_score=score,
        runtime=runtime.name,
        risk="monitor selected by usable capacity" if agent is None else "manual override",
    )
    store.upsert_session(session)
    try:
        runtime.spawn(session)
    except Exception:
        session.status = "failed"
        session.updated_at = iso_now()
        store.upsert_session(session)
        raise
    session.status = "running"
    session.updated_at = iso_now()
    store.upsert_session(session)
    return SpawnResult(session=session, command=command)


def build_task_packet(*, task: str, repo: str, agent: str) -> str:
    return "\n".join(
        [
            "TASK",
            task,
            "",
            "REPO",
            repo,
            "",
            "STATE",
            f"Spawned by Loom for {agent}. Use the repository state on disk as source of truth.",
            "",
            "FILES",
            "Inspect the repo and edit only files needed for the task.",
            "",
            "CONSTRAINTS",
            "Respect existing user changes. Do not run destructive git commands. Verify before final output.",
            "",
            "ASK",
            "Complete the task end to end. If blocked, explain the blocker and the exact next step.",
            "",
            "OUTPUT",
            "Summarize changed files, verification, and remaining risks.",
            "",
        ]
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-").lower()
    return slug[:32] or "repo"


def _shell_join(command: list[str]) -> str:
    return " ".join(_quote(part) for part in command)


def _tmux_error(action: str, exc: subprocess.CalledProcessError) -> str:
    detail = (exc.stderr or exc.stdout or "").strip()
    if detail:
        return f"tmux {action} failed: {detail}"
    return f"tmux {action} failed with exit code {exc.returncode}"


def _tmux_target(session_name: str) -> str:
    return session_name.replace(":", "_")


def _quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:=@+-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"

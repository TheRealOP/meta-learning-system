"""Storage for Loom usage and monitor state."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from loom.models import AgentState, TaskSession, UsageEvent, iso_now


def find_meta_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        if (path / "akms_config.yaml").exists() and (path / "knowledge").exists():
            return path
    package_root = Path(__file__).resolve().parents[3]
    if (package_root.parent / "akms_config.yaml").exists():
        return package_root.parent
    return current


class LoomStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or find_meta_root()
        self.log_dir = self.root / "knowledge" / "logs" / "loom"
        self.ledger_path = self.log_dir / "usage.jsonl"
        self.state_path = self.log_dir / "state.json"
        self.sessions_path = self.log_dir / "sessions.json"
        self.events_log_path = self.log_dir / "events.log"

    def ensure(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def append_event(self, event: UsageEvent) -> None:
        self.ensure()
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_json(), sort_keys=True) + "\n")
        with self.events_log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{event.ended_at} {event.agent} {event.signal} {event.task} {event.reason}\n"
            )

    def read_events(self) -> list[UsageEvent]:
        if not self.ledger_path.exists():
            return []
        events: list[UsageEvent] = []
        with self.ledger_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    events.append(UsageEvent.from_json(json.loads(line)))
        return events

    def write_state(self, states: Iterable[AgentState], selected: str | None) -> None:
        self.ensure()
        payload = {
            "updated_at": iso_now(),
            "recommended_agent": selected,
            "agents": [state.to_json() for state in states],
        }
        self.state_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def read_state(self) -> dict:
        if not self.state_path.exists():
            return {"agents": [], "recommended_agent": None}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write_sessions(self, sessions: Iterable[TaskSession]) -> None:
        self.ensure()
        payload = [session.to_json() for session in sessions]
        self.sessions_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def read_sessions(self) -> list[TaskSession]:
        if not self.sessions_path.exists():
            return []
        payload = json.loads(self.sessions_path.read_text(encoding="utf-8"))
        return [TaskSession.from_json(item) for item in payload]

    def upsert_session(self, session: TaskSession) -> None:
        sessions = [item for item in self.read_sessions() if item.task_id != session.task_id]
        sessions.append(session)
        self.write_sessions(sessions)

    def update_session_status(self, session_name_or_id: str, status: str) -> TaskSession | None:
        sessions = self.read_sessions()
        updated: TaskSession | None = None
        for session in sessions:
            if session.session_name == session_name_or_id or session.task_id == session_name_or_id:
                session.status = status
                session.updated_at = iso_now()
                updated = session
                break
        self.write_sessions(sessions)
        return updated

    def active_task_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for session in self.read_sessions():
            if session.status in {"running", "starting"}:
                counts[session.agent] = counts.get(session.agent, 0) + 1
        return counts

    def task_packet_path(self, task_id: str) -> Path:
        return self.log_dir / "tasks" / f"{task_id}.md"

    def write_task_packet(self, task_id: str, content: str) -> Path:
        self.ensure()
        task_dir = self.log_dir / "tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        path = self.task_packet_path(task_id)
        path.write_text(content, encoding="utf-8")
        return path

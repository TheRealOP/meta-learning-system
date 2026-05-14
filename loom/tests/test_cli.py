from __future__ import annotations

from click.testing import CliRunner

from loom.cli import main
from loom.models import TaskSession, iso_now


def test_status_writes_state(meta_root):
    result = CliRunner().invoke(main, ["--root", str(meta_root), "status"])

    assert result.exit_code == 0
    assert "Loom Activity Monitor" in result.output
    assert (meta_root / "knowledge" / "logs" / "loom" / "state.json").exists()


def test_usage_command(meta_root):
    result = CliRunner().invoke(main, ["--root", str(meta_root), "usage"])

    assert result.exit_code == 0
    assert "codex_cli" in result.output


def test_probe_dry_run_records_events(meta_root):
    result = CliRunner().invoke(main, ["--root", str(meta_root), "probe", "--dry-run"])

    assert result.exit_code == 0
    assert "codex_cli:" in result.output
    assert (meta_root / "knowledge" / "logs" / "loom" / "usage.jsonl").exists()


def test_monitor_once(meta_root):
    result = CliRunner().invoke(main, ["--root", str(meta_root), "monitor", "--once"])

    assert result.exit_code == 0
    assert "Recommended next agent" in result.output


def test_route_outputs_selected_agent(meta_root):
    result = CliRunner().invoke(main, ["--root", str(meta_root), "route", "fix tests"])

    assert result.exit_code == 0
    assert "Selected:" in result.output


def test_run_spawns_routed_session(monkeypatch, meta_root):
    session = TaskSession(
        task_id="abc123",
        session_name="loom:repo:abc123",
        agent="codex_cli",
        task="fix tests",
        repo=str(meta_root),
        status="running",
        command=["codex", "exec", "packet"],
        packet_path=str(meta_root / "packet.md"),
        created_at=iso_now(),
        updated_at=iso_now(),
        routing_reason="available",
        runtime="fake",
    )

    class Result:
        def __init__(self):
            self.session = session

    monkeypatch.setattr("loom.cli.spawn_task", lambda *args, **kwargs: Result())

    result = CliRunner().invoke(main, ["--root", str(meta_root), "run", "fix tests"])

    assert result.exit_code == 0
    assert "Session: loom:repo:abc123" in result.output
    assert "Agent: codex_cli" in result.output


def test_spawn_accepts_agent_alias(monkeypatch, meta_root):
    captured = {}

    def fake_spawn(*args, **kwargs):
        captured.update(kwargs)
        session = TaskSession(
            task_id="abc123",
            session_name="loom:repo:abc123",
            agent=kwargs["agent"],
            task="task",
            repo=str(meta_root),
            status="running",
            command=[],
            packet_path=str(meta_root / "packet.md"),
            created_at=iso_now(),
            updated_at=iso_now(),
            routing_reason="manual agent override",
            runtime="fake",
        )

        class Result:
            def __init__(self):
                self.session = session

        return Result()

    monkeypatch.setattr("loom.cli.spawn_task", fake_spawn)

    result = CliRunner().invoke(
        main, ["--root", str(meta_root), "spawn", "--agent", "claude", "do thing"]
    )

    assert result.exit_code == 0
    assert captured["agent"] == "claude_cli"


def test_sessions_command_outputs_recorded_sessions(meta_root):
    from loom.storage import LoomStore

    store = LoomStore(root=meta_root)
    store.upsert_session(
        TaskSession(
            task_id="abc123",
            session_name="loom:repo:abc123",
            agent="gemini_cli",
            task="do thing",
            repo=str(meta_root),
            status="running",
            command=[],
            packet_path=str(meta_root / "packet.md"),
            created_at=iso_now(),
            updated_at=iso_now(),
        )
    )

    result = CliRunner().invoke(main, ["--root", str(meta_root), "sessions"])

    assert result.exit_code == 0
    assert "loom:repo:abc123" in result.output

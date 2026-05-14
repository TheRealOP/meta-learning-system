from __future__ import annotations

import subprocess
from pathlib import Path

from loom.models import Signal, UsageEvent, iso_now
from loom.runtime import FakeRuntime, RuntimeErrorDetail, TmuxRuntime, build_task_packet, resolve_agent, spawn_task
from loom.storage import LoomStore


def event(agent: str, signal: Signal) -> UsageEvent:
    return UsageEvent(
        agent=agent,
        task="test",
        command=["fake"],
        started_at=iso_now(),
        ended_at=iso_now(),
        duration_ms=1,
        exit_code=0 if signal == Signal.SUCCESS else 1,
        signal=signal.value,
        prompt_tokens=1,
        output_tokens=1,
    )


def test_build_task_packet_uses_caveman_sections():
    packet = build_task_packet(task="fix bug", repo="/repo", agent="codex_cli")

    for section in ["TASK", "REPO", "STATE", "FILES", "CONSTRAINTS", "ASK", "OUTPUT"]:
        assert f"{section}\n" in packet
    assert "fix bug" in packet


def test_resolve_agent_aliases():
    assert resolve_agent("codex") == "codex_cli"
    assert resolve_agent("claude_cli") == "claude_cli"


def test_spawn_task_with_fake_runtime_records_session(meta_root):
    store = LoomStore(root=meta_root)
    runtime = FakeRuntime()

    result = spawn_task(store, "fix tests", agent="codex", repo=Path(meta_root), runtime=runtime)

    assert result.session.status == "running"
    assert result.session.session_name.startswith("loom:")
    assert result.session.packet_path.endswith(".md")
    assert runtime.spawned[0].agent == "codex_cli"
    assert store.read_sessions()[0].task == "fix tests"


def test_spawn_task_routes_around_blocked_agent(meta_root):
    store = LoomStore(root=meta_root)
    store.append_event(event("codex_cli", Signal.QUOTA))
    store.append_event(event("claude_cli", Signal.SUCCESS))
    runtime = FakeRuntime()

    result = spawn_task(store, "implement feature", repo=Path(meta_root), runtime=runtime)

    assert result.session.agent != "codex_cli"
    assert result.session.routing_reason == "available"


def test_active_task_counts_include_running_sessions(meta_root):
    store = LoomStore(root=meta_root)
    spawn_task(store, "one", agent="gemini", repo=Path(meta_root), runtime=FakeRuntime())

    assert store.active_task_counts() == {"gemini_cli": 1}


def test_tmux_stop_failure_is_clean_error(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=args[0],
            stderr="can't find session: does-not-exist",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    try:
        TmuxRuntime().stop("does-not-exist")
    except RuntimeErrorDetail as exc:
        assert "can't find session" in str(exc)
    else:
        raise AssertionError("expected RuntimeErrorDetail")


def test_tmux_runtime_uses_tmux_safe_target_names(monkeypatch, meta_root):
    calls = []
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    def fake_run(*args, **kwargs):
        calls.append(args[0])
        return subprocess.CompletedProcess(args=args[0], returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    session = spawn_task(
        LoomStore(root=meta_root),
        "inspect",
        agent="codex",
        repo=Path(meta_root),
        runtime=TmuxRuntime(),
    ).session

    TmuxRuntime().attach(session.session_name)
    TmuxRuntime().stop(session.session_name)

    assert session.session_name.startswith("loom:")
    assert calls[0][4] == session.session_name.replace(":", "_")
    assert calls[1][-1] == session.session_name.replace(":", "_")
    assert calls[2][-1] == session.session_name.replace(":", "_")

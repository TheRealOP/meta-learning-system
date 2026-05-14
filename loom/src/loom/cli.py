"""Loom CLI."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import click

from loom import __version__
from loom.providers import PROVIDERS, probe_provider
from loom.runtime import RuntimeErrorDetail, TmuxRuntime, resolve_agent, spawn_task
from loom.scoring import aggregate_states, select_agent
from loom.storage import LoomStore


def _store(ctx: click.Context) -> LoomStore:
    root = Path(ctx.obj["root"]).resolve() if ctx.obj.get("root") else None
    return LoomStore(root=root)


@click.group()
@click.version_option(version=__version__, prog_name="loom")
@click.option("--root", type=click.Path(file_okay=False), default=None, help="meta-learning-system root")
@click.pass_context
def main(ctx: click.Context, root: str | None) -> None:
    """Loom activity monitor and router."""
    ctx.ensure_object(dict)
    ctx.obj["root"] = root


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output raw state JSON")
@click.pass_context
def status(ctx: click.Context, as_json: bool) -> None:
    """Show agent availability and routing recommendation."""
    store = _store(ctx)
    states = aggregate_states(store.read_events(), active_tasks=store.active_task_counts())
    selected = select_agent(states)
    store.write_state(states, selected.agent if selected else None)
    if as_json:
        click.echo(json.dumps(store.read_state(), indent=2))
        return
    _print_status(states, selected.agent if selected else None)


@main.command()
@click.option("--once", is_flag=True, help="Print one monitor sample and exit")
@click.option("--interval", default=5, show_default=True, help="Refresh interval in seconds")
@click.pass_context
def monitor(ctx: click.Context, once: bool, interval: int) -> None:
    """Watch the current Loom monitor state."""
    while True:
        store = _store(ctx)
        states = aggregate_states(store.read_events(), active_tasks=store.active_task_counts())
        selected = select_agent(states)
        store.write_state(states, selected.agent if selected else None)
        _print_status(states, selected.agent if selected else None)
        if once:
            return
        time.sleep(interval)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
@click.pass_context
def usage(ctx: click.Context, as_json: bool) -> None:
    """Show local Loom-launched usage totals."""
    store = _store(ctx)
    states = aggregate_states(store.read_events(), active_tasks=store.active_task_counts())
    if as_json:
        click.echo(json.dumps([state.to_json() for state in states], indent=2))
        return
    click.echo("Usage")
    for state in sorted(states, key=lambda item: item.agent):
        click.echo(
            f"  {state.agent}: today={state.calls_today} hour={state.calls_hour} "
            f"recent_failures={state.failures_recent} active={state.active_tasks}"
        )


@main.command()
@click.option("--agent", "agent_key", type=click.Choice(sorted(PROVIDERS)), default=None)
@click.option("--dry-run", is_flag=True, help="Check binaries without launching probes")
@click.pass_context
def probe(ctx: click.Context, agent_key: str | None, dry_run: bool) -> None:
    """Run lightweight provider health probes."""
    store = _store(ctx)
    keys = [agent_key] if agent_key else sorted(PROVIDERS)
    for key in keys:
        event = probe_provider(PROVIDERS[key], dry_run=dry_run)
        store.append_event(event)
        click.echo(f"{key}: {event.signal} ({event.reason})")


@main.command()
@click.argument("task")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
@click.pass_context
def route(ctx: click.Context, task: str, as_json: bool) -> None:
    """Recommend the best available agent for a task."""
    store = _store(ctx)
    states = aggregate_states(store.read_events(), active_tasks=store.active_task_counts())
    selected = select_agent(states)
    store.write_state(states, selected.agent if selected else None)
    payload = {
        "task": task,
        "selected_agent": selected.agent if selected else None,
        "reason": selected.reason if selected else "no providers configured",
        "score": selected.score if selected else 0,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Selected: {payload['selected_agent']}")
    click.echo(f"Score: {payload['score']}")
    click.echo(f"Reason: {payload['reason']}")


@main.command()
@click.argument("goal")
@click.option("--repo", type=click.Path(file_okay=False), default=".", help="Working directory")
@click.pass_context
def run(ctx: click.Context, goal: str, repo: str) -> None:
    """Route a goal to the best available agent and spawn a session."""
    _spawn(ctx, goal, agent=None, repo=repo)


@main.command()
@click.option(
    "--agent",
    "agent_name",
    type=click.Choice(["codex", "claude", "gemini", *sorted(PROVIDERS)]),
    required=True,
    help="Agent to spawn",
)
@click.option("--repo", type=click.Path(file_okay=False), default=".", help="Working directory")
@click.argument("task")
@click.pass_context
def spawn(ctx: click.Context, agent_name: str, repo: str, task: str) -> None:
    """Spawn a task with a specific agent."""
    _spawn(ctx, task, agent=resolve_agent(agent_name), repo=repo)


@main.command(name="sessions")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
@click.pass_context
def sessions_command(ctx: click.Context, as_json: bool) -> None:
    """List Loom task sessions."""
    sessions = _store(ctx).read_sessions()
    if as_json:
        click.echo(json.dumps([session.to_json() for session in sessions], indent=2))
        return
    if not sessions:
        click.echo("No Loom sessions recorded.")
        return
    for session in sessions:
        click.echo(
            f"{session.session_name} {session.status} agent={session.agent} "
            f"repo={session.repo} task={session.task}"
        )


@main.command()
@click.argument("session")
@click.pass_context
def attach(ctx: click.Context, session: str) -> None:
    """Attach to a tmux-backed Loom session."""
    store = _store(ctx)
    found = _find_session(store, session)
    if found and found.runtime != "tmux":
        detail = f"Session uses {found.runtime}; log={found.log_path or found.packet_path}"
        raise click.ClickException(detail)
    try:
        TmuxRuntime().attach(found.session_name if found else session)
    except RuntimeErrorDetail as exc:
        raise click.ClickException(str(exc)) from exc


@main.command()
@click.argument("session")
@click.pass_context
def stop(ctx: click.Context, session: str) -> None:
    """Stop a Loom tmux session and mark it stopped."""
    store = _store(ctx)
    found = _find_session(store, session)
    target = found.session_name if found else session
    if found and found.runtime != "tmux":
        _stop_local_session(found)
        store.update_session_status(target, "stopped")
        click.echo(f"Marked local session stopped: {target}")
        return
    try:
        TmuxRuntime().stop(target)
    except RuntimeErrorDetail as exc:
        if found:
            store.update_session_status(target, "stopped")
            click.echo(f"Marked missing tmux session stopped: {target}")
            click.echo(f"Warning: {exc}", err=True)
            return
        raise click.ClickException(str(exc)) from exc
    store.update_session_status(target, "stopped")
    click.echo(f"Stopped: {target}")


@main.command(name="log")
@click.option("--limit", default=20, show_default=True, help="Number of events to show")
@click.pass_context
def log_command(ctx: click.Context, limit: int) -> None:
    """Show recent Loom usage events."""
    store = _store(ctx)
    events = store.read_events()[-limit:]
    if not events:
        click.echo("No Loom events recorded.")
        return
    for event in events:
        click.echo(f"{event.ended_at} {event.agent} {event.signal} {event.task}")


def _spawn(ctx: click.Context, task: str, *, agent: str | None, repo: str) -> None:
    store = _store(ctx)
    try:
        result = spawn_task(store, task, agent=agent, repo=Path(repo))
    except (RuntimeErrorDetail, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Session: {result.session.session_name}")
    click.echo(f"Agent: {result.session.agent}")
    click.echo(f"Runtime: {result.session.runtime}")
    click.echo(f"Packet: {result.session.packet_path}")
    if result.session.log_path:
        click.echo(f"Log: {result.session.log_path}")
    click.echo(f"Reason: {result.session.routing_reason}")


def _find_session(store: LoomStore, value: str):
    for session in store.read_sessions():
        if session.session_name == value or session.task_id == value:
            return session
    return None


def _stop_local_session(session) -> None:
    if not session.runtime_pid:
        return
    try:
        os.killpg(session.runtime_pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise click.ClickException(f"cannot stop pid {session.runtime_pid}: {exc}") from exc


def _print_status(states, selected: str | None) -> None:
    click.echo("Loom Activity Monitor")
    click.echo(f"Recommended next agent: {selected or 'none'}")
    click.echo()
    for state in sorted(states, key=lambda item: item.agent):
        availability = "available" if state.available else "blocked"
        click.echo(
            f"{state.agent:11} {availability:9} score={state.score:5.1f} "
            f"today={state.calls_today:2d} hour={state.calls_hour:2d} "
            f"active={state.active_tasks:2d} reason={state.reason}"
        )

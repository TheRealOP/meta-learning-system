from __future__ import annotations

from datetime import timedelta

from loom.models import Signal, UsageEvent, iso_now, utc_now
from loom.providers import detect_signal, estimate_tokens
from loom.scoring import aggregate_states, select_agent
from loom.storage import LoomStore


def event(agent: str, signal: Signal, *, hours_ago: int = 0) -> UsageEvent:
    ended = (utc_now() - timedelta(hours=hours_ago)).isoformat()
    return UsageEvent(
        agent=agent,
        task="test",
        command=["fake"],
        started_at=iso_now(),
        ended_at=ended,
        duration_ms=1,
        exit_code=0 if signal == Signal.SUCCESS else 1,
        signal=signal.value,
        prompt_tokens=1,
        output_tokens=1,
    )


def test_store_appends_and_reads_usage(meta_root):
    store = LoomStore(root=meta_root)
    store.append_event(event("codex_cli", Signal.SUCCESS))

    events = store.read_events()

    assert len(events) == 1
    assert events[0].agent == "codex_cli"
    assert (meta_root / "knowledge" / "logs" / "loom" / "usage.jsonl").exists()


def test_detects_quota_auth_timeout_language():
    assert detect_signal("", "quota exceeded", 1) == Signal.QUOTA
    assert detect_signal("", "please login first", 1) == Signal.AUTH
    assert detect_signal("429 too many requests", "", 1) == Signal.RATE_LIMIT
    assert detect_signal("ok", "", 0) == Signal.SUCCESS


def test_estimate_tokens_is_stable():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_quota_event_blocks_agent_and_routes_elsewhere():
    events = [
        event("codex_cli", Signal.QUOTA),
        event("claude_cli", Signal.SUCCESS),
        event("gemini_cli", Signal.SUCCESS),
    ]

    states = aggregate_states(events)
    codex = next(state for state in states if state.agent == "codex_cli")
    selected = select_agent(states)

    assert not codex.available
    assert "cooldown" in codex.reason
    assert selected is not None
    assert selected.agent != "codex_cli"


def test_missing_binary_blocks_agent():
    states = aggregate_states([event("gemini_cli", Signal.MISSING_BINARY)])
    gemini = next(state for state in states if state.agent == "gemini_cli")

    assert not gemini.available
    assert gemini.reason == "binary missing"

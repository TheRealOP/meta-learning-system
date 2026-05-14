"""Aggregate usage and compute routing scores."""

from __future__ import annotations

from datetime import timedelta

from loom.models import AgentState, Signal, UsageEvent, parse_time, utc_now
from loom.providers import PROVIDERS, cooldown_until_for

BLOCKING_SIGNALS = {
    Signal.AUTH.value,
    Signal.QUOTA.value,
    Signal.RATE_LIMIT.value,
    Signal.COOLDOWN.value,
    Signal.MISSING_BINARY.value,
}
FAILURE_SIGNALS = {
    Signal.FAILURE.value,
    Signal.AUTH.value,
    Signal.QUOTA.value,
    Signal.RATE_LIMIT.value,
    Signal.OVERLOAD.value,
    Signal.COOLDOWN.value,
    Signal.TIMEOUT.value,
    Signal.MISSING_BINARY.value,
}


def aggregate_states(events: list[UsageEvent], active_tasks: dict[str, int] | None = None) -> list[AgentState]:
    active_tasks = active_tasks or {}
    now = utc_now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hour_start = now - timedelta(hours=1)
    states: list[AgentState] = []

    for key, provider in PROVIDERS.items():
        agent_events = [event for event in events if event.agent == key]
        calls_today = sum(1 for event in agent_events if (parse_time(event.ended_at) or now) >= today_start)
        calls_hour = sum(1 for event in agent_events if (parse_time(event.ended_at) or now) >= hour_start)
        recent = sorted(agent_events, key=lambda event: event.ended_at)[-8:]
        last = recent[-1] if recent else None
        failures_recent = sum(1 for event in recent if event.signal in FAILURE_SIGNALS)
        signals = [event.signal for event in recent[-4:]]
        cooldown_until = None
        for event in reversed(recent):
            until = cooldown_until_for(Signal(event.signal)) if event.signal in Signal._value2member_map_ else None
            if until and (parse_time(until) or now) > now:
                cooldown_until = until
                break

        reason = "available"
        available = True
        if last and last.signal == Signal.MISSING_BINARY.value:
            available = False
            reason = "binary missing"
        elif last and last.signal == Signal.AUTH.value:
            available = False
            reason = "auth required"
        elif cooldown_until:
            available = False
            reason = f"cooldown until {cooldown_until}"
        elif calls_hour >= provider.hourly_budget:
            available = False
            reason = "local hourly budget exhausted"
        elif calls_today >= provider.daily_budget:
            available = False
            reason = "local daily budget exhausted"
        elif last and last.signal in BLOCKING_SIGNALS:
            available = False
            reason = last.signal

        usage_penalty = (calls_hour / provider.hourly_budget) * 25 + (calls_today / provider.daily_budget) * 25
        failure_penalty = min(35, failures_recent * 8)
        active_penalty = active_tasks.get(key, 0) * 12
        risk_score = min(100.0, usage_penalty + failure_penalty + active_penalty)
        score = max(0.0, 100.0 - risk_score)
        if not available:
            score = min(score, 5.0)

        states.append(
            AgentState(
                agent=key,
                available=available,
                score=round(score, 2),
                reason=reason,
                calls_today=calls_today,
                calls_hour=calls_hour,
                last_call_at=last.ended_at if last else None,
                cooldown_until=cooldown_until,
                active_tasks=active_tasks.get(key, 0),
                failures_recent=failures_recent,
                risk_score=round(risk_score, 2),
                signals=signals,
            )
        )
    return sorted(states, key=lambda state: state.score, reverse=True)


def select_agent(states: list[AgentState]) -> AgentState | None:
    for state in states:
        if state.available:
            return state
    return states[0] if states else None

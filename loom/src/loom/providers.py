"""Provider registry and subprocess probing."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from datetime import timedelta

from loom.models import Provider, Signal, UsageEvent, iso_now, utc_now


PROVIDERS: dict[str, Provider] = {
    "codex_cli": Provider(
        key="codex_cli",
        display_name="Codex CLI",
        binary="codex",
        probe_args=("--version",),
        daily_budget=80,
        hourly_budget=12,
    ),
    "claude_cli": Provider(
        key="claude_cli",
        display_name="Claude CLI",
        binary="claude",
        probe_args=("--version",),
        daily_budget=80,
        hourly_budget=12,
    ),
    "gemini_cli": Provider(
        key="gemini_cli",
        display_name="Gemini CLI",
        binary="gemini",
        probe_args=("--version",),
        daily_budget=120,
        hourly_budget=20,
    ),
}


SIGNAL_PATTERNS: list[tuple[Signal, re.Pattern[str]]] = [
    (Signal.AUTH, re.compile(r"\b(auth|login|unauthorized|forbidden|api key|credentials?)\b", re.I)),
    (Signal.QUOTA, re.compile(r"\b(quota|usage limit|limit exceeded|billing|subscription)\b", re.I)),
    (Signal.RATE_LIMIT, re.compile(r"\b(rate.?limit|too many requests|429)\b", re.I)),
    (Signal.OVERLOAD, re.compile(r"\b(overloaded|capacity|try again later|temporarily unavailable)\b", re.I)),
    (Signal.COOLDOWN, re.compile(r"\b(cooldown|wait \d+|retry after)\b", re.I)),
]


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def detect_signal(stdout: str, stderr: str, exit_code: int | None) -> Signal:
    combined = f"{stdout}\n{stderr}"
    for signal, pattern in SIGNAL_PATTERNS:
        if pattern.search(combined):
            return signal
    if exit_code == 0:
        return Signal.SUCCESS
    return Signal.FAILURE


def cooldown_until_for(signal: Signal) -> str | None:
    now = utc_now()
    if signal in {Signal.QUOTA, Signal.COOLDOWN}:
        return (now + timedelta(hours=4)).isoformat()
    if signal == Signal.RATE_LIMIT:
        return (now + timedelta(minutes=30)).isoformat()
    if signal == Signal.OVERLOAD:
        return (now + timedelta(minutes=10)).isoformat()
    return None


def provider_command(provider: Provider, task: str | None = None) -> list[str]:
    if task is None:
        return [provider.binary, *provider.probe_args]
    if provider.key == "codex_cli":
        return [provider.binary, "exec", task]
    if provider.key == "claude_cli":
        return [provider.binary, "-p", task]
    if provider.key == "gemini_cli":
        return [provider.binary, "-p", task]
    return [provider.binary, task]


def probe_provider(provider: Provider, *, dry_run: bool = False) -> UsageEvent:
    command = provider_command(provider)
    started = iso_now()
    started_perf = time.monotonic()
    if dry_run:
        signal = Signal.SUCCESS if shutil.which(provider.binary) else Signal.MISSING_BINARY
        ended = iso_now()
        return UsageEvent(
            agent=provider.key,
            task="probe --dry-run",
            command=command,
            started_at=started,
            ended_at=ended,
            duration_ms=int((time.monotonic() - started_perf) * 1000),
            exit_code=0 if signal == Signal.SUCCESS else None,
            signal=signal.value,
            prompt_tokens=0,
            output_tokens=0,
            reason="binary found" if signal == Signal.SUCCESS else "binary not found",
        )

    if not shutil.which(provider.binary):
        ended = iso_now()
        return UsageEvent(
            agent=provider.key,
            task="probe",
            command=command,
            started_at=started,
            ended_at=ended,
            duration_ms=int((time.monotonic() - started_perf) * 1000),
            exit_code=None,
            signal=Signal.MISSING_BINARY.value,
            prompt_tokens=0,
            output_tokens=0,
            reason="binary not found",
        )

    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=provider.timeout_seconds,
            check=False,
        )
        signal = detect_signal(result.stdout, result.stderr, result.returncode)
        ended = iso_now()
        return UsageEvent(
            agent=provider.key,
            task="probe",
            command=command,
            started_at=started,
            ended_at=ended,
            duration_ms=int((time.monotonic() - started_perf) * 1000),
            exit_code=result.returncode,
            signal=signal.value,
            prompt_tokens=0,
            output_tokens=estimate_tokens(result.stdout + result.stderr),
            stdout_excerpt=result.stdout[:500],
            stderr_excerpt=result.stderr[:500],
            reason="probe completed",
        )
    except subprocess.TimeoutExpired as exc:
        ended = iso_now()
        return UsageEvent(
            agent=provider.key,
            task="probe",
            command=command,
            started_at=started,
            ended_at=ended,
            duration_ms=int((time.monotonic() - started_perf) * 1000),
            exit_code=None,
            signal=Signal.TIMEOUT.value,
            prompt_tokens=0,
            output_tokens=estimate_tokens((exc.stdout or "") + (exc.stderr or "")),
            stdout_excerpt=str(exc.stdout or "")[:500],
            stderr_excerpt=str(exc.stderr or "")[:500],
            reason="probe timed out",
        )

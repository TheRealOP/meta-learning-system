from __future__ import annotations

import subprocess

from loom.models import Signal
from loom.providers import PROVIDERS, probe_provider


def test_probe_dry_run_missing_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: None)

    event = probe_provider(PROVIDERS["codex_cli"], dry_run=True)

    assert event.signal == Signal.MISSING_BINARY.value


def test_probe_success(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="version 1", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    event = probe_provider(PROVIDERS["claude_cli"])

    assert event.signal == Signal.SUCCESS.value
    assert event.exit_code == 0


def test_probe_auth_failure(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="login required")

    monkeypatch.setattr(subprocess, "run", fake_run)

    event = probe_provider(PROVIDERS["gemini_cli"])

    assert event.signal == Signal.AUTH.value


def test_probe_timeout(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=1, output="partial", stderr="slow")

    monkeypatch.setattr(subprocess, "run", fake_run)

    event = probe_provider(PROVIDERS["codex_cli"])

    assert event.signal == Signal.TIMEOUT.value

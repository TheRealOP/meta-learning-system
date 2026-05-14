from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def meta_root(tmp_path: Path) -> Path:
    (tmp_path / "knowledge" / "logs").mkdir(parents=True)
    (tmp_path / "akms_config.yaml").write_text("knowledge: {}\n", encoding="utf-8")
    return tmp_path

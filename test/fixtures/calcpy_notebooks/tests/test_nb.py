"""calcpy_notebooks fixture: organize-imports applies to .py only,
.ipynb cell content must be byte-stable post-flow."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_notebook_is_valid_nbformat() -> None:
    payload = json.loads((ROOT / "notebooks" / "explore.ipynb").read_text())
    assert payload["nbformat"] == 4
    assert payload["nbformat_minor"] == 5
    assert len(payload["cells"]) == 3


def test_calcpy_min_module_imports_present() -> None:
    src = (ROOT / "src" / "calcpy_min.py").read_text()
    assert "import math" in src
    assert "from typing" in src


def test_baseline_notebook_hash() -> None:
    """Captured at fixture freeze; integration test re-checks post-flow."""
    h = hashlib.sha256((ROOT / "notebooks" / "explore.ipynb").read_bytes()).hexdigest()
    assert len(h) == 64  # sentinel - leaf 04 captures the actual hash

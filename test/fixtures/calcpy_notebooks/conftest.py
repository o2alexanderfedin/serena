"""Make the fixture's `src/` importable without `pip install -e .`.

Tests in `tests/test_nb.py` currently read files via `Path` and never
import `calcpy_min`, so this conftest is not strictly required today.
It is added for parity with the other two calcpy_* sub-fixtures so any
future test that imports `calcpy_min` works without an editable install.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

"""Make the fixture package importable without `pip install -e .`.

This is a fixture-only convenience so `python -m pytest tests/` works
from the sub-fixture root. Production code never does this.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

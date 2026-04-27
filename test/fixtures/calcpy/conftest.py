"""Make the calcpy fixture package importable without `pip install -e .`.

This is a fixture-only convenience so `python -m pytest tests/` works
from the calcpy fixture root. Production code never does this. Mirrors
the pattern used by sibling sub-fixtures (calcpy_circular et al.).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

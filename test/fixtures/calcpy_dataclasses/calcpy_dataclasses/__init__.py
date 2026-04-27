"""calcpy_dataclasses - inline-flow fixture for Stage 1H T5.

Five @dataclass declarations: four in :mod:`.models`, one already
extracted to :mod:`.sub.extracted` as the target shape for the
inline-flow integration test.
"""
from __future__ import annotations

from . import models
from .sub import extracted

__all__ = ["models", "extracted"]

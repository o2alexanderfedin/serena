"""Developer-host pytest plugin (opt-in).

Activates ONLY when ``O2_SCALPEL_LOCAL_HOST=1`` is exported in the
environment. When active it sets ``CARGO_BUILD_RUSTC=rustc`` to defeat
the developer's global ``~/.cargo/config.toml`` ``rust-fv-driver``
wrapper (broken dyld lookup); see
``docs/superpowers/plans/spike-results/PROGRESS.md:60`` for the origin
of the workaround and ``docs/superpowers/plans/stage-1h-results/PROGRESS.md:88``
for the closure note.

CI does NOT set the flag, so its environment remains clean — the
workaround is host-specific and not masked.

Single source of truth for the developer-facing context lives in
``docs/dev/host-rustc-shim.md``.
"""
from __future__ import annotations

import os
from typing import Any


def pytest_configure(config: Any) -> None:
    """Pytest hook: opt-in env shim for developer hosts only.

    The ``config`` parameter is required by pytest's hook signature even
    though we do not use it.
    """
    del config  # unused; required by pytest hook signature
    if os.environ.get("O2_SCALPEL_LOCAL_HOST") == "1":
        os.environ.setdefault("CARGO_BUILD_RUSTC", "rustc")

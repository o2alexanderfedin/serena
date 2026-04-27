"""v1.1 Stream 5 / Leaf 05 — Engine config knob: Settings field tests.

Asserts the runtime engine-selection knob exposed via
``serena.config.engine.Settings``:

* Defaults to ``serena-fork`` when ``O2_SCALPEL_ENGINE`` is unset.
* Accepts the env var verbatim when it matches a registered engine id.
* Rejects unknown engine ids at Settings construction time
  (pydantic-validated, not lazy).
* The validator queries the live ``EngineRegistry.default()`` so a
  newly ``register(...)``-ed engine is immediately accepted with no
  Settings code change (critic R1 — registry-validated ``str``, not
  a single-member ``Literal``).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from serena.config.engine import Settings


class _StubEngine:
    """Minimal :class:`serena.engine.registry.EngineProtocol` impl for tests."""

    def apply_workspace_edit(self, edit: dict[str, Any]) -> int:  # pragma: no cover
        return 0


def test_engine_default_is_serena_fork(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("O2_SCALPEL_ENGINE", raising=False)
    s = Settings()
    assert s.engine == "serena-fork"


def test_engine_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("O2_SCALPEL_ENGINE", "serena-fork")
    s = Settings()
    assert s.engine == "serena-fork"


def test_engine_unknown_value_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("O2_SCALPEL_ENGINE", "definitely-not-real")
    with pytest.raises(ValidationError):
        Settings()


def test_engine_accepts_newly_registered_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registering a new engine at runtime extends the accepted-value set
    without a Settings code change — confirms the registry-backed seam (R1).
    """
    from serena.engine.registry import EngineRegistry

    EngineRegistry.default().register("native", _StubEngine)
    try:
        monkeypatch.setenv("O2_SCALPEL_ENGINE", "native")
        s = Settings()
        assert s.engine == "native"
    finally:
        EngineRegistry.default()._factories.pop("native", None)

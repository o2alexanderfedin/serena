"""v1.1 Stream 5 / Leaf 05 — runtime engine_id wiring tests.

Asserts the bootstrap-side contract from the spec's Task 3:

* ``ScalpelRuntime`` resolves :class:`serena.config.engine.Settings`
  at construction and stashes the result on ``engine_id``.
* The resolved id matches whatever ``O2_SCALPEL_ENGINE`` was set to
  (here: the only registered engine, ``serena-fork``).

Spec-API adaptation note: the spec-original test imported
``serena.bootstrap.build_runtime``, which does not exist in this
codebase. Per the leaf brief we picked option (a) — minimum surface,
follows existing patterns — and added ``engine_id`` directly to the
``ScalpelRuntime`` singleton instead of introducing a new
``serena.bootstrap`` wrapper module. The contract the test asserts
is the same: a runtime built under a given engine env exposes that
engine id.
"""

from __future__ import annotations

import pytest

from serena.tools.scalpel_runtime import ScalpelRuntime


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    """Reset the singleton so each test sees a fresh ``engine_id``."""
    ScalpelRuntime.reset_for_testing()


def test_runtime_uses_engine_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("O2_SCALPEL_ENGINE", "serena-fork")
    rt = ScalpelRuntime.instance()
    assert rt.engine_id == "serena-fork"


def test_runtime_default_engine_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("O2_SCALPEL_ENGINE", raising=False)
    rt = ScalpelRuntime.instance()
    assert rt.engine_id == "serena-fork"

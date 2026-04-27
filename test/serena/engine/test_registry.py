"""v1.1 Stream 5 / Leaf 05 — engine registry tests.

Asserts the seam contract on
:class:`serena.engine.registry.EngineRegistry`:

* The default singleton resolves the bundled ``serena-fork`` engine
  to a factory whose product satisfies the engine protocol (i.e. has
  an ``apply_workspace_edit`` attribute).
* ``get(...)`` raises ``KeyError`` for unknown ids.
* ``keys()`` enumerates the registered ids (so callers — notably the
  ``Settings.engine`` validator — can list them).
"""

from __future__ import annotations

import pytest

from serena.engine.registry import EngineRegistry


def test_registry_returns_factory_for_known_engine() -> None:
    reg = EngineRegistry.default()
    factory = reg.get("serena-fork")
    instance = factory()
    assert hasattr(instance, "apply_workspace_edit")


def test_registry_raises_on_unknown() -> None:
    reg = EngineRegistry.default()
    with pytest.raises(KeyError):
        reg.get("ghost")


def test_registry_keys_lists_registered_ids() -> None:
    reg = EngineRegistry.default()
    assert "serena-fork" in reg.keys()

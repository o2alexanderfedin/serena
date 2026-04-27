"""v1.1 Stream 5 / Leaf 05 — engine factory registry.

Process-wide registry mapping engine-id strings to factories.
``Settings.engine`` (in :mod:`serena.config.engine`) validates the
``O2_SCALPEL_ENGINE`` env value against this registry so unknown ids
fail fast at construction time.

Adding a new engine is one ``register(...)`` call — no Settings code
change required (the validator on ``Settings.engine`` queries this
registry at validation time). See critic R1 for rationale (registry-
validated ``str`` rather than a single-member ``Literal``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EngineProtocol(Protocol):
    """Minimal protocol an LSP-write engine must satisfy.

    Today the bundled ``serena-fork`` engine wraps
    :func:`serena.tools.scalpel_facades._apply_workspace_edit_to_disk`,
    which returns the count of TextEdits actually applied. Future
    engines (``native``, ``lspee``) will satisfy the same shape.
    """

    def apply_workspace_edit(self, edit: dict[str, Any]) -> int: ...


class _SerenaForkEngine:
    """Concrete engine wrapping the production WorkspaceEdit applier.

    The production applier callable is
    :func:`serena.tools.scalpel_facades._apply_workspace_edit_to_disk`
    (Spec API note — the spec referenced ``build_default_applier``,
    which doesn't exist in this codebase). Wrapping it in a tiny class
    gives the registry an instance with the ``apply_workspace_edit``
    attribute the engine protocol expects, without forcing every call
    site through a new abstraction yet.
    """

    def apply_workspace_edit(self, edit: dict[str, Any]) -> int:
        from serena.tools.scalpel_facades import _apply_workspace_edit_to_disk

        return _apply_workspace_edit_to_disk(edit)


def _build_serena_fork_engine() -> _SerenaForkEngine:
    """Default factory for the bundled ``serena-fork`` engine.

    Kept as a module-level function (not a lambda) so the registry's
    debug repr and stack traces stay readable.
    """
    return _SerenaForkEngine()


class EngineRegistry:
    """Process-wide registry mapping engine-id strings to factories.

    Adding a new engine is one ``register(...)`` call — no Settings
    code change required (the validator on ``Settings.engine`` queries
    this registry at validation time). See critic R1 for rationale.

    The default singleton is built lazily so import order stays
    forgiving: the first call to :meth:`default` triggers registration
    of the bundled ``serena-fork`` engine via a function reference
    (the underlying applier is only imported when the engine is
    actually instantiated, see :class:`_SerenaForkEngine`).
    """

    _singleton: "EngineRegistry | None" = None

    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], EngineProtocol]] = {}

    def register(
        self, engine_id: str, factory: Callable[[], EngineProtocol],
    ) -> None:
        self._factories[engine_id] = factory

    def get(self, engine_id: str) -> Callable[[], EngineProtocol]:
        try:
            return self._factories[engine_id]
        except KeyError as exc:
            raise KeyError(
                f"engine '{engine_id}' is not registered",
            ) from exc

    def keys(self) -> Iterable[str]:
        return self._factories.keys()

    @classmethod
    def default(cls) -> "EngineRegistry":
        """Return the process-wide singleton, building it on first use.

        Critic S5 — the import of the bundled-engine factory stays
        encapsulated inside :class:`_SerenaForkEngine` (its
        ``apply_workspace_edit`` method is the only place the applier
        symbol is referenced). Importing the applier at module top
        would risk a settings-load loop because Settings imports this
        module to validate ``engine``, and the applier itself lives
        in :mod:`serena.tools.scalpel_facades`, which transitively
        imports a great deal of the runtime.
        """
        if cls._singleton is None:
            reg = cls()
            reg.register("serena-fork", _build_serena_fork_engine)
            cls._singleton = reg
        return cls._singleton


__all__ = ["EngineProtocol", "EngineRegistry"]

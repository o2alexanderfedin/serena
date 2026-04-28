"""Stream 6 / Leaf E — LeanStrategy unit tests.

Mirrors ``test_java_strategy.py``: identity constants, Protocol
conformance, single-server build, and registry membership. The strategy
is single-LSP (no multi-server merge for Lean — ``lean --server`` is the
only Lean 4 language server), so ``build_servers`` returns exactly one entry.

Key constraint: the ``code_action_allow_list`` must contain ONLY
``"quickfix"`` — no rename, no extract, no refactor. This is the core
safety contract for a dependent-type theorem prover (see lean_strategy.py
module docstring for the full rationale). These tests explicitly verify
the *absence* of unsafe kinds.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_lean_strategy_imports() -> None:
    from serena.refactoring.lean_strategy import LeanStrategy

    del LeanStrategy  # import-success is the assertion


def test_lean_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy
    from serena.refactoring.lean_strategy import LeanStrategy

    assert isinstance(LeanStrategy(pool=MagicMock()), LanguageStrategy)


def test_lean_identity_constants() -> None:
    from serena.refactoring.lean_strategy import LeanStrategy

    s = LeanStrategy(pool=MagicMock())
    assert s.language_id == "lean"
    # Standard Lean 4 source extension.
    assert ".lean" in s.extension_allow_list
    # No unrelated suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list
    assert ".ts" not in s.extension_allow_list
    assert ".go" not in s.extension_allow_list
    assert ".cpp" not in s.extension_allow_list
    assert ".java" not in s.extension_allow_list
    assert ".md" not in s.extension_allow_list


def test_lean_code_action_allow_list_contains_only_quickfix() -> None:
    """The allow-list MUST be exactly {'quickfix'}.

    This is the non-negotiable safety invariant for a theorem prover:
    quickfix tactic suggestions are semantics-preserving; rename and
    extract are NOT (see lean_strategy.py module docstring).
    """
    from serena.refactoring.lean_strategy import LeanStrategy

    s = LeanStrategy(pool=MagicMock())
    assert s.code_action_allow_list == frozenset({"quickfix"}), (
        f"LeanStrategy.code_action_allow_list must be exactly {{'quickfix'}}; "
        f"got {s.code_action_allow_list!r}"
    )


def test_lean_code_action_allow_list_does_not_contain_rename() -> None:
    """Rename is UNSAFE for theorem provers — must not appear in allow-list."""
    from serena.refactoring.lean_strategy import LeanStrategy

    s = LeanStrategy(pool=MagicMock())
    # None of the refactor.* or rename-related kinds must be present.
    unsafe_kinds = {
        "refactor",
        "refactor.extract",
        "refactor.extract.method",
        "refactor.extract.variable",
        "refactor.inline",
        "refactor.rewrite",
        "rename",
    }
    intersection = s.code_action_allow_list & unsafe_kinds
    assert intersection == frozenset(), (
        f"LeanStrategy must not include unsafe rename/extract kinds; "
        f"found {intersection!r} in code_action_allow_list"
    )


def test_execute_command_whitelist_is_empty() -> None:
    """lean --server does not expose workspace/executeCommand verbs."""
    from serena.refactoring.lean_strategy import LeanStrategy

    assert LeanStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_lean_entry() -> None:
    from serena.refactoring.lean_strategy import LeanStrategy
    from serena.refactoring.lsp_pool import LspPoolKey

    fake_server = MagicMock(name="lean-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = LeanStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-lean-project"))

    assert set(out.keys()) == {"lean"}
    assert out["lean"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "lean"


def test_strategy_registry_includes_lean4() -> None:
    """STRATEGY_REGISTRY[Language.LEAN4] must resolve to LeanStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.lean_strategy import LeanStrategy
    from solidlsp.ls_config import Language

    assert Language.LEAN4 in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.LEAN4] is LeanStrategy


def test_provenance_literal_includes_lean() -> None:
    """ProvenanceLiteral must include 'lean' for catalog attribution."""
    from typing import get_args

    from serena.refactoring.multi_server import ProvenanceLiteral

    assert "lean" in get_args(ProvenanceLiteral)


def test_default_source_server_by_language_includes_lean() -> None:
    """_DEFAULT_SOURCE_SERVER_BY_LANGUAGE must have a 'lean' → 'lean' entry."""
    from serena.refactoring.capabilities import _DEFAULT_SOURCE_SERVER_BY_LANGUAGE  # pyright: ignore[reportPrivateUsage]

    assert _DEFAULT_SOURCE_SERVER_BY_LANGUAGE.get("lean") == "lean"


def test_adapter_map_includes_lean() -> None:
    """_adapter_map() must return a 'lean' → LeanServer mapping."""
    from serena.refactoring.capabilities import _adapter_map  # pyright: ignore[reportPrivateUsage]
    from solidlsp.language_servers.lean_server import LeanServer

    assert _adapter_map().get("lean") is LeanServer


def test_adapter_attribution_order_includes_lean() -> None:
    """_ADAPTER_ATTRIBUTION_ORDER must have a 'lean' entry with ('lean',)."""
    from serena.refactoring.capabilities import _ADAPTER_ATTRIBUTION_ORDER  # pyright: ignore[reportPrivateUsage]

    assert _ADAPTER_ATTRIBUTION_ORDER.get("lean") == ("lean",)


def test_installer_registry_includes_lean() -> None:
    """_installer_registry() must map 'lean' → LeanInstaller."""
    from serena.installer.lean_installer import LeanInstaller
    from serena.tools.scalpel_primitives import _installer_registry  # pyright: ignore[reportPrivateUsage]

    assert _installer_registry().get("lean") is LeanInstaller

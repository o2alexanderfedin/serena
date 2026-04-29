"""Stream 6 / Leaf I — CsharpStrategy unit tests.

Mirrors ``test_java_strategy.py``: identity constants, Protocol
conformance, single-server build, and registry membership. The strategy
is single-LSP (no multi-server merge for C# — csharp-ls is the sole server),
so ``build_servers`` returns exactly one entry keyed ``"csharp-ls"``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_csharp_strategy_imports() -> None:
    from serena.refactoring.csharp_strategy import CsharpStrategy

    del CsharpStrategy  # import-success is the assertion


def test_csharp_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.csharp_strategy import CsharpStrategy
    from serena.refactoring.language_strategy import LanguageStrategy

    assert isinstance(CsharpStrategy(pool=MagicMock()), LanguageStrategy)


def test_csharp_identity_constants() -> None:
    from serena.refactoring.csharp_strategy import CsharpStrategy

    s = CsharpStrategy(pool=MagicMock())
    assert s.language_id == "csharp"
    # Standard C# source.
    assert ".cs" in s.extension_allow_list
    assert ".csx" in s.extension_allow_list
    # No unrelated suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list
    assert ".ts" not in s.extension_allow_list
    assert ".go" not in s.extension_allow_list
    assert ".java" not in s.extension_allow_list
    assert ".cpp" not in s.extension_allow_list
    assert ".md" not in s.extension_allow_list


def test_csharp_code_action_allow_list_covers_csharp_ls_kinds() -> None:
    """The allow-list must cover the csharp-ls advertised code action kinds."""
    from serena.refactoring.csharp_strategy import CsharpStrategy

    s = CsharpStrategy(pool=MagicMock())
    # Quick-fix.
    assert "quickfix" in s.code_action_allow_list
    # Import management.
    assert "source.organizeImports" in s.code_action_allow_list
    # Extract refactors.
    assert "refactor.extract" in s.code_action_allow_list
    assert "refactor.extract.method" in s.code_action_allow_list
    assert "refactor.extract.variable" in s.code_action_allow_list
    # Inline refactors.
    assert "refactor.inline" in s.code_action_allow_list
    assert "refactor.inline.method" in s.code_action_allow_list
    # Rewrite refactors.
    assert "refactor.rewrite" in s.code_action_allow_list
    # Generic refactor parent kind.
    assert "refactor" in s.code_action_allow_list


def test_execute_command_whitelist_is_empty() -> None:
    """csharp-ls does not expose workspace/executeCommand verbs from the strategy layer."""
    from serena.refactoring.csharp_strategy import CsharpStrategy

    assert CsharpStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_csharp_ls_entry() -> None:
    from serena.refactoring.csharp_strategy import CsharpStrategy
    from serena.refactoring.lsp_pool import LspPoolKey

    fake_server = MagicMock(name="csharp-ls-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = CsharpStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-csharp-project"))

    assert set(out.keys()) == {"csharp-ls"}
    assert out["csharp-ls"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "csharp"


def test_strategy_registry_includes_csharp() -> None:
    """STRATEGY_REGISTRY[Language.CSHARP] must resolve to CsharpStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.csharp_strategy import CsharpStrategy
    from solidlsp.ls_config import Language

    assert Language.CSHARP in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.CSHARP] is CsharpStrategy


def test_provenance_literal_includes_csharp_ls() -> None:
    """ProvenanceLiteral must include 'csharp-ls' for catalog attribution."""
    from typing import get_args

    from serena.refactoring.multi_server import ProvenanceLiteral

    assert "csharp-ls" in get_args(ProvenanceLiteral)


def test_default_source_server_by_language_includes_csharp() -> None:
    """_DEFAULT_SOURCE_SERVER_BY_LANGUAGE must have a 'csharp' → 'csharp-ls' entry."""
    from serena.refactoring.capabilities import _DEFAULT_SOURCE_SERVER_BY_LANGUAGE  # pyright: ignore[reportPrivateUsage]

    assert _DEFAULT_SOURCE_SERVER_BY_LANGUAGE.get("csharp") == "csharp-ls"


def test_adapter_map_includes_csharp_ls() -> None:
    """_adapter_map() must return a 'csharp-ls' → CsharpLsServer mapping."""
    from serena.refactoring.capabilities import _adapter_map  # pyright: ignore[reportPrivateUsage]
    from solidlsp.language_servers.csharp_ls_server import CsharpLsServer

    assert _adapter_map().get("csharp-ls") is CsharpLsServer


def test_adapter_attribution_order_includes_csharp() -> None:
    """_ADAPTER_ATTRIBUTION_ORDER must have a 'csharp' entry with ('csharp-ls',)."""
    from serena.refactoring.capabilities import _ADAPTER_ATTRIBUTION_ORDER  # pyright: ignore[reportPrivateUsage]

    assert _ADAPTER_ATTRIBUTION_ORDER.get("csharp") == ("csharp-ls",)


def test_installer_registry_includes_csharp() -> None:
    """_installer_registry() must map 'csharp' → CsharpLsInstaller."""
    from serena.installer.csharp_ls_installer import CsharpLsInstaller
    from serena.tools.scalpel_primitives import _installer_registry  # pyright: ignore[reportPrivateUsage]

    assert _installer_registry().get("csharp") is CsharpLsInstaller

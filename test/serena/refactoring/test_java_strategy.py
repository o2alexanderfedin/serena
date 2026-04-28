"""Stream 6 / Leaf D — JavaStrategy unit tests.

Mirrors ``test_cpp_strategy.py``: identity constants, Protocol
conformance, single-server build, and registry membership. The strategy
is single-LSP (no multi-server merge for Java — jdtls is canonical),
so ``build_servers`` returns exactly one entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_java_strategy_imports() -> None:
    from serena.refactoring.java_strategy import JavaStrategy

    del JavaStrategy  # import-success is the assertion


def test_java_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.java_strategy import JavaStrategy
    from serena.refactoring.language_strategy import LanguageStrategy

    assert isinstance(JavaStrategy(pool=MagicMock()), LanguageStrategy)


def test_java_identity_constants() -> None:
    from serena.refactoring.java_strategy import JavaStrategy

    s = JavaStrategy(pool=MagicMock())
    assert s.language_id == "java"
    # Standard Java source.
    assert ".java" in s.extension_allow_list
    # No unrelated suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list
    assert ".ts" not in s.extension_allow_list
    assert ".go" not in s.extension_allow_list
    assert ".cpp" not in s.extension_allow_list
    assert ".md" not in s.extension_allow_list


def test_java_code_action_allow_list_covers_jdtls_kinds() -> None:
    """The allow-list must cover the jdtls advertised code action kinds."""
    from serena.refactoring.java_strategy import JavaStrategy

    s = JavaStrategy(pool=MagicMock())
    # Import management.
    assert "source.organizeImports" in s.code_action_allow_list
    # Code generation.
    assert "source.generate.constructor" in s.code_action_allow_list
    assert "source.generate.hashCodeEquals" in s.code_action_allow_list
    assert "source.generate.toString" in s.code_action_allow_list
    assert "source.generate.accessors" in s.code_action_allow_list
    assert "source.generate.overrideMethods" in s.code_action_allow_list
    assert "source.generate.delegateMethods" in s.code_action_allow_list
    # Extract refactors.
    assert "refactor.extract" in s.code_action_allow_list
    assert "refactor.extract.method" in s.code_action_allow_list
    assert "refactor.extract.variable" in s.code_action_allow_list
    assert "refactor.extract.field" in s.code_action_allow_list
    assert "refactor.extract.interface" in s.code_action_allow_list
    # Inline refactors.
    assert "refactor.inline" in s.code_action_allow_list
    # Rewrite refactors.
    assert "refactor.rewrite" in s.code_action_allow_list
    # Quick-fix.
    assert "quickfix" in s.code_action_allow_list
    # Generic refactor parent kind.
    assert "refactor" in s.code_action_allow_list


def test_execute_command_whitelist_is_empty() -> None:
    """jdtls does not expose workspace/executeCommand verbs from the strategy layer."""
    from serena.refactoring.java_strategy import JavaStrategy

    assert JavaStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_jdtls_entry() -> None:
    from serena.refactoring.java_strategy import JavaStrategy
    from serena.refactoring.lsp_pool import LspPoolKey

    fake_server = MagicMock(name="jdtls-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = JavaStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-java-project"))

    assert set(out.keys()) == {"jdtls"}
    assert out["jdtls"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "java"


def test_strategy_registry_includes_java() -> None:
    """STRATEGY_REGISTRY[Language.JAVA] must resolve to JavaStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.java_strategy import JavaStrategy
    from solidlsp.ls_config import Language

    assert Language.JAVA in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.JAVA] is JavaStrategy


def test_provenance_literal_includes_jdtls() -> None:
    """ProvenanceLiteral must include 'jdtls' for catalog attribution."""
    from typing import get_args

    from serena.refactoring.multi_server import ProvenanceLiteral

    assert "jdtls" in get_args(ProvenanceLiteral)


def test_default_source_server_by_language_includes_java() -> None:
    """_DEFAULT_SOURCE_SERVER_BY_LANGUAGE must have a 'java' → 'jdtls' entry."""
    from serena.refactoring.capabilities import _DEFAULT_SOURCE_SERVER_BY_LANGUAGE  # pyright: ignore[reportPrivateUsage]

    assert _DEFAULT_SOURCE_SERVER_BY_LANGUAGE.get("java") == "jdtls"


def test_adapter_map_includes_jdtls() -> None:
    """_adapter_map() must return a 'jdtls' → JdtlsServer mapping."""
    from serena.refactoring.capabilities import _adapter_map  # pyright: ignore[reportPrivateUsage]
    from solidlsp.language_servers.jdtls_server import JdtlsServer

    assert _adapter_map().get("jdtls") is JdtlsServer


def test_adapter_attribution_order_includes_java() -> None:
    """_ADAPTER_ATTRIBUTION_ORDER must have a 'java' entry with ('jdtls',)."""
    from serena.refactoring.capabilities import _ADAPTER_ATTRIBUTION_ORDER  # pyright: ignore[reportPrivateUsage]

    assert _ADAPTER_ATTRIBUTION_ORDER.get("java") == ("jdtls",)


def test_installer_registry_includes_java() -> None:
    """_installer_registry() must map 'java' → JdtlsInstaller."""
    from serena.installer.jdtls_installer import JdtlsInstaller
    from serena.tools.scalpel_primitives import _installer_registry  # pyright: ignore[reportPrivateUsage]

    assert _installer_registry().get("java") is JdtlsInstaller

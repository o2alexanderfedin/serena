"""Stream 6 / Leaf C — CppStrategy unit tests.

Mirrors ``test_golang_strategy.py``: identity constants, Protocol
conformance, single-server build, and registry membership. The strategy
is single-LSP (no multi-server merge for C/C++ — clangd is canonical),
so ``build_servers`` returns exactly one entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_cpp_strategy_imports() -> None:
    from serena.refactoring.cpp_strategy import CppStrategy

    del CppStrategy  # import-success is the assertion


def test_cpp_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.cpp_strategy import CppStrategy
    from serena.refactoring.language_strategy import LanguageStrategy

    assert isinstance(CppStrategy(pool=MagicMock()), LanguageStrategy)


def test_cpp_identity_constants() -> None:
    from serena.refactoring.cpp_strategy import CppStrategy

    s = CppStrategy(pool=MagicMock())
    assert s.language_id == "cpp"
    # C source.
    assert ".c" in s.extension_allow_list
    # C++ source variants.
    assert ".cc" in s.extension_allow_list
    assert ".cpp" in s.extension_allow_list
    assert ".cxx" in s.extension_allow_list
    assert ".c++" in s.extension_allow_list
    # Headers.
    assert ".h" in s.extension_allow_list
    assert ".hpp" in s.extension_allow_list
    # Template/inline implementations.
    assert ".ipp" in s.extension_allow_list
    assert ".inl" in s.extension_allow_list
    # No unrelated suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list
    assert ".ts" not in s.extension_allow_list
    assert ".go" not in s.extension_allow_list
    assert ".md" not in s.extension_allow_list


def test_cpp_code_action_allow_list_covers_clangd_kinds() -> None:
    """The allow-list must cover the clangd advertised code action kinds."""
    from serena.refactoring.cpp_strategy import CppStrategy

    s = CppStrategy(pool=MagicMock())
    # Include management.
    assert "source.organizeImports" in s.code_action_allow_list
    # Auto-fix all.
    assert "source.fixAll.clangd" in s.code_action_allow_list
    # Extract refactors.
    assert "refactor.extract" in s.code_action_allow_list
    assert "refactor.extract.function" in s.code_action_allow_list
    # Inline refactors.
    assert "refactor.inline" in s.code_action_allow_list
    # Quick-fix.
    assert "quickfix" in s.code_action_allow_list
    # Generic refactor parent kind.
    assert "refactor" in s.code_action_allow_list


def test_execute_command_whitelist_is_empty() -> None:
    """clangd does not expose workspace/executeCommand verbs."""
    from serena.refactoring.cpp_strategy import CppStrategy

    assert CppStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_clangd_entry() -> None:
    from serena.refactoring.cpp_strategy import CppStrategy
    from serena.refactoring.lsp_pool import LspPoolKey

    fake_server = MagicMock(name="clangd-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = CppStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-cpp-project"))

    assert set(out.keys()) == {"clangd"}
    assert out["clangd"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "cpp"


def test_strategy_registry_includes_cpp() -> None:
    """STRATEGY_REGISTRY[Language.CPP] must resolve to CppStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.cpp_strategy import CppStrategy
    from solidlsp.ls_config import Language

    assert Language.CPP in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.CPP] is CppStrategy

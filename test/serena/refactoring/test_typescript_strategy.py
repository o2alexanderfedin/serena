"""Stream 6 / Leaf A — TypescriptStrategy unit tests.

Mirrors ``test_markdown_strategy.py``: identity constants, Protocol
conformance, single-server build, and registry membership. The strategy
is single-LSP (no multi-server merge for TypeScript — vtsls is canonical),
so ``build_servers`` returns exactly one entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_typescript_strategy_imports() -> None:
    from serena.refactoring.typescript_strategy import TypescriptStrategy

    del TypescriptStrategy  # import-success is the assertion


def test_typescript_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy
    from serena.refactoring.typescript_strategy import TypescriptStrategy

    assert isinstance(TypescriptStrategy(pool=MagicMock()), LanguageStrategy)


def test_typescript_identity_constants() -> None:
    from serena.refactoring.typescript_strategy import TypescriptStrategy

    s = TypescriptStrategy(pool=MagicMock())
    assert s.language_id == "typescript"
    # Core TypeScript extensions.
    assert ".ts" in s.extension_allow_list
    assert ".tsx" in s.extension_allow_list
    # JavaScript variants.
    assert ".js" in s.extension_allow_list
    assert ".jsx" in s.extension_allow_list
    # ESM / CommonJS variants.
    assert ".mts" in s.extension_allow_list
    assert ".cts" in s.extension_allow_list
    assert ".mjs" in s.extension_allow_list
    assert ".cjs" in s.extension_allow_list
    # No unrelated suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list
    assert ".md" not in s.extension_allow_list


def test_typescript_code_action_allow_list_covers_vtsls_kinds() -> None:
    """The allow-list must cover the vtsls advertised code action kinds."""
    from serena.refactoring.typescript_strategy import TypescriptStrategy

    s = TypescriptStrategy(pool=MagicMock())
    # Source-level actions.
    assert "source.organizeImports" in s.code_action_allow_list
    assert "source.fixAll" in s.code_action_allow_list
    # Extract refactors.
    assert "refactor.extract" in s.code_action_allow_list
    assert "refactor.extract.function" in s.code_action_allow_list
    assert "refactor.extract.variable" in s.code_action_allow_list
    # Inline refactors.
    assert "refactor.inline" in s.code_action_allow_list
    # Quick-fix.
    assert "quickfix" in s.code_action_allow_list


def test_execute_command_whitelist_is_empty() -> None:
    """vtsls does not expose workspace/executeCommand verbs."""
    from serena.refactoring.typescript_strategy import TypescriptStrategy

    assert TypescriptStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_vtsls_entry() -> None:
    from serena.refactoring.lsp_pool import LspPoolKey
    from serena.refactoring.typescript_strategy import TypescriptStrategy

    fake_server = MagicMock(name="vtsls-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = TypescriptStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-ts-project"))

    assert set(out.keys()) == {"vtsls"}
    assert out["vtsls"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "typescript"


def test_strategy_registry_includes_typescript() -> None:
    """STRATEGY_REGISTRY[Language.TYPESCRIPT] must resolve to TypescriptStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.typescript_strategy import TypescriptStrategy
    from solidlsp.ls_config import Language

    assert Language.TYPESCRIPT in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.TYPESCRIPT] is TypescriptStrategy

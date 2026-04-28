"""Stream 6 / Leaf B — GolangStrategy unit tests.

Mirrors ``test_typescript_strategy.py``: identity constants, Protocol
conformance, single-server build, and registry membership. The strategy
is single-LSP (no multi-server merge for Go — gopls is canonical),
so ``build_servers`` returns exactly one entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_golang_strategy_imports() -> None:
    from serena.refactoring.golang_strategy import GolangStrategy

    del GolangStrategy  # import-success is the assertion


def test_golang_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.golang_strategy import GolangStrategy
    from serena.refactoring.language_strategy import LanguageStrategy

    assert isinstance(GolangStrategy(pool=MagicMock()), LanguageStrategy)


def test_golang_identity_constants() -> None:
    from serena.refactoring.golang_strategy import GolangStrategy

    s = GolangStrategy(pool=MagicMock())
    assert s.language_id == "go"
    # Only Go extension.
    assert ".go" in s.extension_allow_list
    # No unrelated suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list
    assert ".ts" not in s.extension_allow_list
    assert ".md" not in s.extension_allow_list


def test_golang_code_action_allow_list_covers_gopls_kinds() -> None:
    """The allow-list must cover the gopls advertised code action kinds."""
    from serena.refactoring.golang_strategy import GolangStrategy

    s = GolangStrategy(pool=MagicMock())
    # Source-level actions.
    assert "source.organizeImports" in s.code_action_allow_list
    assert "source.fixAll" in s.code_action_allow_list
    # Extract refactors.
    assert "refactor.extract" in s.code_action_allow_list
    assert "refactor.extract.function" in s.code_action_allow_list
    assert "refactor.extract.variable" in s.code_action_allow_list
    # Inline refactors.
    assert "refactor.inline" in s.code_action_allow_list
    # Rewrite refactors.
    assert "refactor.rewrite" in s.code_action_allow_list
    # Quick-fix.
    assert "quickfix" in s.code_action_allow_list


def test_execute_command_whitelist_is_empty() -> None:
    """gopls does not expose workspace/executeCommand verbs."""
    from serena.refactoring.golang_strategy import GolangStrategy

    assert GolangStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_gopls_entry() -> None:
    from serena.refactoring.golang_strategy import GolangStrategy
    from serena.refactoring.lsp_pool import LspPoolKey

    fake_server = MagicMock(name="gopls-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = GolangStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-go-project"))

    assert set(out.keys()) == {"gopls"}
    assert out["gopls"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "go"


def test_strategy_registry_includes_go() -> None:
    """STRATEGY_REGISTRY[Language.GO] must resolve to GolangStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.golang_strategy import GolangStrategy
    from solidlsp.ls_config import Language

    assert Language.GO in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.GO] is GolangStrategy

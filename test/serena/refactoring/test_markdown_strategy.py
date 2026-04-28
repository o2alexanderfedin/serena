"""v1.1.1 Leaf 01 — MarkdownStrategy unit tests.

Mirrors ``test_stage_1e_t2_rust_strategy_skeleton.py``: identity
constants, Protocol conformance, single-server build, and registry
membership. The strategy is single-LSP (no multi-server merge for
markdown — marksman is canonical), so ``build_servers`` returns
exactly one entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_markdown_strategy_imports() -> None:
    from serena.refactoring.markdown_strategy import MarkdownStrategy

    del MarkdownStrategy  # import-success is the assertion


def test_markdown_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy
    from serena.refactoring.markdown_strategy import MarkdownStrategy

    assert isinstance(MarkdownStrategy(pool=MagicMock()), LanguageStrategy)


def test_markdown_identity_constants() -> None:
    from serena.refactoring.markdown_strategy import MarkdownStrategy

    s = MarkdownStrategy(pool=MagicMock())
    assert s.language_id == "markdown"
    assert ".md" in s.extension_allow_list
    assert ".markdown" in s.extension_allow_list
    assert ".mdx" in s.extension_allow_list
    # No source-code suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list


def test_markdown_code_action_allow_list_is_empty() -> None:
    """marksman exposes no code actions (per its 2026-02-08 docs)."""
    from serena.refactoring.markdown_strategy import MarkdownStrategy

    s = MarkdownStrategy(pool=MagicMock())
    assert s.code_action_allow_list == frozenset()


def test_execute_command_whitelist_is_empty() -> None:
    """marksman does not expose any workspace/executeCommand verbs."""
    from serena.refactoring.markdown_strategy import MarkdownStrategy

    assert MarkdownStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_marksman_entry() -> None:
    from serena.refactoring.lsp_pool import LspPoolKey
    from serena.refactoring.markdown_strategy import MarkdownStrategy

    fake_server = MagicMock(name="marksman-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = MarkdownStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-md-project"))

    assert set(out.keys()) == {"marksman"}
    assert out["marksman"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "markdown"


def test_strategy_registry_includes_markdown() -> None:
    """STRATEGY_REGISTRY[Language.MARKDOWN] must resolve to MarkdownStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.markdown_strategy import MarkdownStrategy
    from solidlsp.ls_config import Language

    assert Language.MARKDOWN in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.MARKDOWN] is MarkdownStrategy

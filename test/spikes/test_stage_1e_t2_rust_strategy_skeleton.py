"""T2 — RustStrategy skeleton: Protocol conformance + identity constants."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_rust_strategy_imports() -> None:
    from serena.refactoring.rust_strategy import RustStrategy

    del RustStrategy  # import-success is the assertion


def test_rust_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy
    from serena.refactoring.rust_strategy import RustStrategy

    assert isinstance(RustStrategy(pool=MagicMock()), LanguageStrategy)


def test_rust_identity_constants() -> None:
    from serena.refactoring.rust_strategy import RustStrategy

    s = RustStrategy(pool=MagicMock())
    assert s.language_id == "rust"
    assert ".rs" in s.extension_allow_list
    # No other suffix accepted.
    assert s.extension_allow_list == frozenset({".rs"})


def test_rust_code_action_allow_list_contains_assist_families() -> None:
    from serena.refactoring.rust_strategy import RustStrategy

    s = RustStrategy(pool=MagicMock())
    # Per LSP §3.18.1 prefix rule, "refactor.extract" matches assist
    # kinds like "refactor.extract.assist".
    assert "refactor.extract" in s.code_action_allow_list
    assert "quickfix" in s.code_action_allow_list


def test_build_servers_returns_single_rust_analyzer_entry() -> None:
    from serena.refactoring.lsp_pool import LspPoolKey
    from serena.refactoring.rust_strategy import RustStrategy

    fake_server = MagicMock(name="rust-analyzer-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = RustStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-rust-project"))

    assert set(out.keys()) == {"rust-analyzer"}
    assert out["rust-analyzer"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "rust"


def test_build_servers_rejects_path_outside_workspace_to_existing_root() -> None:
    """build_servers does NOT validate the root path beyond passing it to the
    pool — workspace-boundary enforcement lives in the applier (Stage 1B/1D)."""
    from serena.refactoring.rust_strategy import RustStrategy

    pool = MagicMock()
    pool.acquire.return_value = MagicMock()
    strat = RustStrategy(pool=pool)
    # Path does not need to exist; pool.acquire owns spawn semantics.
    strat.build_servers(Path("/does/not/exist"))

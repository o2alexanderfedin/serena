"""Stage 1J T0 — bootstrap smoke test for ``_FakeStrategy`` fixtures.

These fixtures power every later Stage 1J render test, so we lock their
shape with a tiny smoke pass before any code is written.
"""

from __future__ import annotations


def test_fake_strategy_rust_has_two_facades(fake_strategy_rust) -> None:
    assert fake_strategy_rust.language == "rust"
    assert fake_strategy_rust.display_name == "Rust"
    assert fake_strategy_rust.file_extensions == (".rs",)
    assert fake_strategy_rust.lsp_server_cmd == ("rust-analyzer",)
    assert len(fake_strategy_rust.facades) == 2
    assert fake_strategy_rust.facades[0].name == "split_file"
    assert fake_strategy_rust.facades[1].name == "rename_symbol"


def test_fake_strategy_python_has_one_facade(fake_strategy_python) -> None:
    assert fake_strategy_python.language == "python"
    assert fake_strategy_python.facades[0].primitive_chain == (
        "textDocument/codeAction",
    )

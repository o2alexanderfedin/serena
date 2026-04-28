"""v1.1.1 Leaf 01 — marksman boot smoke test.

Proves the ``MarksmanLanguageServer`` adapter can:
  1. Spawn ``marksman server`` against a tmp_path workspace.
  2. Complete the LSP initialize handshake.
  3. Return at least one symbol for ``textDocument/documentSymbol``
     against a markdown file containing an H1 heading.

Skips cleanly when ``marksman`` is not on PATH (skip pattern is for
tests only — production wiring expects Leaf 03 ``LspInstaller`` to
provision the binary).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from solidlsp.language_servers.marksman_server import MarksmanLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings


def _require_binary(name: str) -> str:
    """Local copy of ``test/integration/conftest.py:176`` to keep this module
    independent of the rust/python integration fixture machinery."""
    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} not on PATH; integration smoke requires it")
    return found


def test_marksman_boots_and_returns_document_symbols(tmp_path: Path) -> None:
    """Boot marksman, parse a single .md file, assert ≥1 heading symbol."""
    _require_binary("marksman")

    # Minimal fixture — one markdown file with two headings.
    md_path = tmp_path / "intro.md"
    md_path.write_text(
        "# Top Heading\n"
        "\n"
        "Some prose.\n"
        "\n"
        "## Sub Heading\n"
        "\n"
        "More prose.\n",
        encoding="utf-8",
    )

    cfg = LanguageServerConfig(code_language=Language.MARKDOWN)
    srv = MarksmanLanguageServer(cfg, str(tmp_path), SolidLSPSettings())

    with srv.start_server():
        document_symbols = srv.request_document_symbols("intro.md")
        all_symbols, _root_symbols = document_symbols.get_all_symbols_and_roots()

    assert len(all_symbols) >= 1, (
        f"marksman returned no symbols for intro.md; got {all_symbols!r}"
    )
    names = [s["name"] for s in all_symbols]
    # marksman emits headings as their text; "# Top Heading" → "Top Heading".
    assert any("Top Heading" in n for n in names), (
        f"H1 'Top Heading' missing from marksman symbols: {names!r}"
    )

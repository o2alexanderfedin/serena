"""T6 — RuffServer adapter (native ruff server, push-mode diagnostics)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

RUFF_AVAILABLE = shutil.which("ruff") is not None or os.environ.get("CI") == "true"


def test_ruff_server_imports() -> None:
    from solidlsp.language_servers.ruff_server import RuffServer

    del RuffServer  # import-success is the assertion


def test_ruff_subclasses_solid_language_server() -> None:
    from solidlsp.language_servers.ruff_server import RuffServer
    from solidlsp.ls import SolidLanguageServer

    assert issubclass(RuffServer, SolidLanguageServer)


def test_ruff_advertises_organize_imports_kind() -> None:
    """Initialize params declare codeAction support for source.organizeImports."""
    from typing import Any, cast

    from solidlsp.language_servers.ruff_server import RuffServer

    # Cast to Any to navigate optional TypedDict keys without per-key guards.
    params = cast(dict[str, Any], RuffServer._get_initialize_params("/tmp/anywhere"))
    cak = (
        params["capabilities"]["textDocument"]["codeAction"]
        ["codeActionLiteralSupport"]["codeActionKind"]["valueSet"]
    )
    assert "source.organizeImports" in cak
    assert "quickfix" in cak
    assert "source.fixAll" in cak


@pytest.mark.skipif(not RUFF_AVAILABLE, reason="ruff not installed")
def test_ruff_boots_and_offers_organize_imports(tmp_path: Path) -> None:
    """Real-LSP boot smoke: ruff offers source.organizeImports on a messy file."""
    from solidlsp.language_servers.ruff_server import RuffServer
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    src = tmp_path / "messy.py"
    # Imports out of order + unused — ruff will offer organize + remove-unused.
    src.write_text(
        "import sys\n"
        "import os\n"
        "from typing import Any, Dict\n"
        "print(os.getcwd())\n"
    )

    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    srv = RuffServer(cfg, str(tmp_path), SolidLSPSettings())
    with srv.start_server():
        with srv.open_file("messy.py"):
            actions = srv.request_code_actions(
                str(src),
                start={"line": 0, "character": 0},
                end={"line": 3, "character": 0},
                only=["source.organizeImports"],
            )
        assert actions, f"ruff must offer source.organizeImports; got {actions}"

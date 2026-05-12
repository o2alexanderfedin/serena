"""T3 — PylspServer adapter spawn + initialize round-trip."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

PYLSP_AVAILABLE = shutil.which("pylsp") is not None or os.environ.get("CI") == "true"


def test_pylsp_server_imports() -> None:
    from solidlsp.language_servers.pylsp_server import PylspServer

    del PylspServer  # import-success is the assertion


def test_pylsp_server_subclasses_solid_language_server() -> None:
    from solidlsp.language_servers.pylsp_server import PylspServer
    from solidlsp.ls import SolidLanguageServer

    assert issubclass(PylspServer, SolidLanguageServer)


def test_pylsp_server_advertises_python_language() -> None:
    """Construction-time identity — does not boot the subprocess."""
    from solidlsp.language_servers.pylsp_server import PylspServer
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    srv = PylspServer(cfg, str(Path.cwd()), SolidLSPSettings())
    assert srv.language == "python"


@pytest.mark.skipif(not PYLSP_AVAILABLE, reason="pylsp not installed (install with [python-lsps] extra)")
def test_pylsp_server_boots_and_initializes(tmp_path: Path) -> None:
    """Real-LSP boot smoke: start_server() must complete without raising
    and the server must respond to a trivial document/symbol request.

    Marked skipif so CI environments without the extra still pass T3 import-only.
    """
    from solidlsp.language_servers.pylsp_server import PylspServer
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    (tmp_path / "x.py").write_text("def hello() -> int:\n    return 1\n")
    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    srv = PylspServer(cfg, str(tmp_path), SolidLSPSettings())
    with srv.start_server_context():
        symbols = srv.request_document_symbols("x.py")
        all_symbols = list(symbols.iter_symbols())
        assert any("hello" in str(s.get("name", "")) for s in all_symbols), all_symbols

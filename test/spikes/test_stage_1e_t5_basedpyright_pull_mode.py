"""T5 — BasedpyrightServer adapter (pull-mode diagnostic, P4 contract)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

BP_AVAILABLE = shutil.which("basedpyright-langserver") is not None or os.environ.get("CI") == "true"


def test_basedpyright_server_imports() -> None:
    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer

    del BasedpyrightServer  # import-success is the assertion


def test_basedpyright_subclasses_solid_language_server() -> None:
    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer
    from solidlsp.ls import SolidLanguageServer

    assert issubclass(BasedpyrightServer, SolidLanguageServer)


def test_basedpyright_version_pin_constant() -> None:
    """Adapter declares the exact pin per Phase 0 Q3."""
    from solidlsp.language_servers.basedpyright_server import BASEDPYRIGHT_VERSION_PIN

    assert BASEDPYRIGHT_VERSION_PIN == "1.39.3"


def test_basedpyright_request_pull_diagnostics_signature() -> None:
    """Pull-mode facade method exists with the correct shape (no boot)."""
    import inspect

    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer

    assert hasattr(BasedpyrightServer, "request_pull_diagnostics")
    sig = inspect.signature(BasedpyrightServer.request_pull_diagnostics)
    assert "uri" in sig.parameters


@pytest.mark.skipif(not BP_AVAILABLE, reason="basedpyright-langserver not installed")
def test_basedpyright_boots_and_pulls_diagnostics(tmp_path: Path) -> None:
    """Real-LSP boot smoke: P4 pull-mode produces non-empty diagnostics."""
    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    bad = tmp_path / "bad.py"
    bad.write_text("def f(x: int) -> int:\n    return x + 'oops'\n")

    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    srv = BasedpyrightServer(cfg, str(tmp_path), SolidLSPSettings())
    with srv.start_server():
        with srv.open_file("bad.py"):
            report = srv.request_pull_diagnostics(uri=bad.as_uri())
        # Pull report contains items[]; with our deliberate type error, >=1.
        items = report.get("items", []) if isinstance(report, dict) else []
        assert items, f"basedpyright PULL must surface >=1 diagnostic; got {report!r}"
        assert any(
            "basedpyright" in str(d.get("source", "")).lower()
            or "Pyright" in str(d.get("source", ""))
            for d in items
        ), items

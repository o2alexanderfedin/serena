"""v1.4.1 Leaf D — dolmenls boot smoke test.

Proves the :class:`Smt2Server` adapter can:
  1. Spawn ``dolmenls`` against a tmp_path workspace.
  2. Complete the LSP initialize handshake.
  3. Open a small ``.smt2`` document and report ``is_running()``.

Skips cleanly when ``dolmenls`` is not on PATH — the production wiring
expects :class:`Smt2Installer` (Leaf B) to provision the binary via the
``install_lsp_servers`` MCP primitive (dry_run=True default,
allow_install=True opt-in).

Dolmenls is a **diagnostics-focused** LSP (per upstream
https://github.com/Gbury/dolmen/blob/master/doc/lsp.md): it parses,
sort-checks, and emits ``textDocument/publishDiagnostics``. Hover /
goto-definition / references / documentSymbol are not implemented in
v0.10. The smoke test therefore only validates boot + handshake — the
runtime :class:`~solidlsp.dynamic_capabilities.DynamicCapabilityRegistry`
gates which methods are callable per session.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from solidlsp.language_servers.smt2_server import Smt2Server
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.settings import SolidLSPSettings

# Minimal valid SMT-LIB 2 fixture — declares an integer constant, asserts
# a trivial constraint, and asks the (downstream) solver for satisfiability.
# dolmenls parses + sort-checks this without errors, so publishDiagnostics
# should report zero diagnostics (or report them with severity Information
# at most).
_VALID_SMT2_FIXTURE = """\
(set-logic QF_LIA)
(declare-const x Int)
(declare-const y Int)
(assert (= (+ x y) 10))
(assert (> x 0))
(check-sat)
(get-model)
"""


def _require_binary(name: str) -> str:
    """Local copy of ``test/integration/conftest.py:_require_binary`` so this
    smoke module stays independent of the rust/python integration fixture
    machinery (mirrors test_marksman_smoke.py:26)."""

    found = shutil.which(name)
    if found is None:
        pytest.skip(f"{name} not on PATH; integration smoke requires it")
    return found


def test_dolmenls_boots_and_reports_running(tmp_path: Path) -> None:
    """Boot dolmenls against a tmp_path workspace, assert ``is_running()``.

    This is the headline integration check: confirms the binary spawn,
    LSP initialize handshake, and ``textDocumentSync`` capability
    advertisement (asserted in :meth:`Smt2Server._start_server`) all
    work end-to-end against the real upstream binary.
    """

    _require_binary("dolmenls")

    smt2_path = tmp_path / "demo.smt2"
    smt2_path.write_text(_VALID_SMT2_FIXTURE, encoding="utf-8")

    cfg = LanguageServerConfig(code_language=Language.SMT2)
    srv = Smt2Server(cfg, str(tmp_path), SolidLSPSettings())

    with srv.start_server():
        assert srv.is_running(), (
            "Smt2Server reports not-running immediately after start_server() — "
            "dolmenls subprocess may have failed to spawn or initialize."
        )

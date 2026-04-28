"""Stream 6 / Leaf H — :class:`ProblogInstaller`.

ProbLog (https://problog.readthedocs.io/) is a **research-mode** probabilistic
logic programming language.  It has two installation components:

1. **ProbLog inference engine** — the Python package that provides the
   ``problog`` CLI and Python API:

     ``pip install problog``

2. **LSP backend** — ProbLog has no dedicated LSP server.  This installer
   piggybacks on the SWI-Prolog ``lsp_server`` pack (shared with Prolog) to
   provide syntax-level diagnostics.  The pack is installed by
   ``PrologInstaller`` — this installer checks for its presence but delegates
   the install command to the same SWI-Prolog pack mechanism.

**Detection strategy:**

``detect_installed()`` reports present=True only when **both** components are
available:
  - The ``problog`` Python package is importable (detects the inference engine).
  - The ``swipl`` binary is on PATH AND the ``lsp_server`` pack is installed
    (detects the LSP backend).

The version reported is the ``problog`` package version (``problog --version``
or ``python -m problog --version``).

**Install command:**

The install command installs the ProbLog inference engine via ``pip``.
The SWI-Prolog / lsp_server pack half is intentionally NOT driven by this
installer (use ``PrologInstaller`` for that) to avoid conflating two separate
install steps in a single ``_install_command`` call.

If ``swipl`` + ``lsp_server`` is absent, ``detect_installed()`` returns
``present=False`` with a version string showing which half is missing, and
the install command surfaces ``pip install problog`` for the inference engine.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["ProblogInstaller"]


_VERSION_TIMEOUT_S = 5.0
_PACK_TIMEOUT_S = 8.0

# ``problog --version`` or ``python -m problog --version`` prints e.g.:
# "problog 2.2.4"
_PROBLOG_VERSION_RE = re.compile(r"problog\s+([\d.]+(?:-\S+)?)")
# Fallback: plain version number on its own line
_PLAIN_VERSION_RE = re.compile(r"^([\d]+\.[\d]+(?:\.[\d]+)?)")


class ProblogInstaller(LspInstaller):
    """Install / detect the ProbLog inference engine (+ swipl LSP check).

    The installer drives the ``problog`` pip package.  The LSP backend
    (``swipl`` + ``lsp_server`` pack) must be installed separately via
    ``PrologInstaller``.
    """

    language: ClassVar[str] = "problog"
    binary_name: ClassVar[str] = "problog"

    def detect_installed(self) -> InstalledStatus:
        """Report present=True when problog (pip) AND swipl+lsp_server are available."""
        problog_version = self._probe_problog_version()
        swipl_lsp_ok = self._probe_swipl_lsp()

        if problog_version is None:
            return InstalledStatus(present=False, version=None, path=None)

        # problog is installed; check for the LSP backend
        if not swipl_lsp_ok:
            # Return present=False with a descriptive version tag so the caller
            # can surface "problog engine OK but LSP backend missing".
            return InstalledStatus(
                present=False,
                version=f"{problog_version}+lsp-backend-missing",
                path=shutil.which("problog"),
            )

        return InstalledStatus(
            present=True,
            version=problog_version,
            path=shutil.which("problog"),
        )

    def latest_available(self) -> str | None:
        """Returns ``None``: PyPI version detection requires a live network call.

        Users can update via ``pip install --upgrade problog``.
        """
        return None

    def _install_command(self) -> tuple[str, ...]:
        """Return the pip install command for the ProbLog inference engine.

        The LSP backend (swipl + lsp_server pack) must be installed separately
        via PrologInstaller.  This installer only drives the pip half.
        """
        return (sys.executable, "-m", "pip", "install", "problog")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_problog_version(self) -> str | None:
        """Try ``python -m problog --version`` to detect the installed version."""
        try:
            completed = subprocess.run(  # noqa: S603
                (sys.executable, "-m", "problog", "--version"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_VERSION_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        out = (completed.stdout or completed.stderr or "").strip()
        if not out:
            return None
        match = _PROBLOG_VERSION_RE.search(out)
        if match:
            return match.group(1)
        # Fallback: plain version line (some versions emit just "2.2.4")
        match2 = _PLAIN_VERSION_RE.search(out)
        if match2:
            return match2.group(1)
        return None

    def _probe_swipl_lsp(self) -> bool:
        """Return True if swipl + lsp_server pack are both available."""
        swipl = shutil.which("swipl")
        if swipl is None:
            return False
        version_goal = "pack_property(lsp_server, version(_)), halt ; halt"
        try:
            completed = subprocess.run(  # noqa: S603
                (swipl, "-g", version_goal, "-t", "halt"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_PACK_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return False
        # The goal writes nothing but exits 0 on success; non-zero on failure.
        # Note: pack_property/2 throws if the pack is absent, which causes
        # halt/0 to exit 1.  The "; halt" alternative ensures clean exit
        # with code 0 when the pack IS present.
        return completed.returncode == 0

"""Stream 6 / Leaf F — :class:`Smt2Installer`.

**LSP ecosystem status (as of 2026-04-27):**

No production-quality, standalone LSP server for SMT-LIB 2 exists.  The
candidates investigated were:

  - VSCode extension wrappers (``smt-z3-vscode`` and similar) that bundle
    solver-specific diagnostics but do not expose a generic stdio LSP
    endpoint for use outside VS Code.
  - GitHub searches for ``smt2-lsp``, ``smt-lsp``, ``smtlib lsp`` all
    return 404 or unmaintained stubs.
  - SMT solvers (Z3, CVC5, Yices) expose command-line interfaces, not LSP.

**Design decision — installer stub raises NotImplementedError:**

The installer is present so that:
  1. ``scalpel_install_lsp_servers`` can probe the ``smt2`` slot and surface
     an actionable message rather than silently skipping the language.
  2. When a production SMT2 LSP eventually ships, only this file needs
     updating (the strategy, adapter, and capability catalog are already wired).

``detect_installed()`` always returns ``InstalledStatus(present=False, ...)``
because there is no binary to detect.

``_install_command()`` raises ``NotImplementedError`` with a guidance message
explaining the current ecosystem gap and pointing users to community resources
where they can track progress.
"""

from __future__ import annotations

import platform
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["Smt2Installer"]


class Smt2Installer(LspInstaller):
    """Installer stub for the SMT-LIB 2 language server.

    No production SMT2 LSP exists as of 2026-04-27.  This installer is
    shipped to preserve the seam: ``scalpel_install_lsp_servers`` can probe
    the ``smt2`` slot and surface a clear guidance message rather than
    silently skipping the language.

    When a production SMT-LIB 2 LSP server ships:
      1. Remove the ``NotImplementedError`` in ``_install_command``.
      2. Implement ``_install_command`` to return the real install argv.
      3. Update ``binary_name`` to the real binary.
      4. Update ``detect_installed`` to probe the real binary.
      5. Update ``Smt2Server._SMT2_LSP_BINARY`` to match.
      6. Re-run ``pytest --update-catalog-baseline`` to refresh the golden
         capability baseline.
    """

    language: ClassVar[str] = "smt2"
    binary_name: ClassVar[str] = "smt2-lsp"  # placeholder — no binary exists yet

    def detect_installed(self) -> InstalledStatus:
        """Always reports not-installed: no SMT2 LSP binary exists yet."""
        return InstalledStatus(present=False, version=None, path=None)

    def latest_available(self) -> str | None:
        """Returns ``None``: no release channel exists for an SMT2 LSP yet."""
        return None

    def _install_command(self) -> tuple[str, ...]:
        """Raise ``NotImplementedError`` with ecosystem-gap guidance.

        No production SMT-LIB 2 LSP server is available.  Users who need
        SMT-LIB support can track community progress at:

          - https://smtlib.cs.uiowa.edu/ (SMT-LIB standard homepage)
          - https://github.com/Z3Prover/z3 (Z3 solver — may add LSP support)
          - https://cvc5.github.io/ (CVC5 solver — may add LSP support)

        Workarounds available today:
          - Use VS Code with the ``smt-z3-vscode`` extension for basic
            syntax highlighting and Z3-backed diagnostics within VS Code only.
          - Use ``z3 <file.smt2>`` from the command line for solver feedback.
        """
        system = platform.system()
        raise NotImplementedError(
            f"No production SMT-LIB 2 LSP server is available on this {system} host "
            f"(or any platform as of 2026-04-27).\n\n"
            f"The SMT-LIB 2 language server slot is reserved for when a stable server "
            f"ships.  Until then, options are:\n"
            f"  • VS Code with the 'smt-z3-vscode' extension (VS Code only, no stdio LSP)\n"
            f"  • Direct solver invocation: z3 <file.smt2> or cvc5 <file.smt2>\n\n"
            f"Track community progress at:\n"
            f"  https://smtlib.cs.uiowa.edu/\n"
            f"  https://github.com/Z3Prover/z3\n"
            f"  https://cvc5.github.io/\n"
        )

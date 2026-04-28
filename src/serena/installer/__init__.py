"""v1.1.1 Leaf 03 — LSP installer infrastructure.

Per ``project_lsp_installer_requirement.md`` the o2-scalpel plugin must
install AND update the LSP servers it drives, not assume they are
pre-installed on PATH. ``marksman`` is the v1.1.1 proving ground; v1.2
back-ports the contract to ``rust-analyzer`` / ``pylsp`` /
``basedpyright`` / ``ruff`` / ``clippy``.

The package exposes:

* :class:`LspInstaller` — abstract base for one LSP-server installer.
* :class:`InstalledStatus` — frozen pydantic boundary model returned by
  :meth:`LspInstaller.detect_installed`.
* :class:`InstallResult` — frozen pydantic boundary model returned by
  :meth:`LspInstaller.install` / :meth:`LspInstaller.update`.
* :class:`MarksmanInstaller` — first concrete subclass (v1.1.1).
* :class:`RustAnalyzerInstaller` — Rust LSP via ``rustup component add`` (v1.2).
* :class:`PylspInstaller` — Python LSP via ``pipx install`` + pylsp-rope inject (v1.2).
* :class:`BasedpyrightInstaller` — Python LSP via ``pipx install`` (v1.2).
* :class:`RuffInstaller` — Python lint+format LSP via ``pipx install`` (v1.2).
* :class:`ClippyInstaller` — Rust lint LSP via ``rustup component add`` (v1.2).

Safety: :meth:`LspInstaller.install` / :meth:`LspInstaller.update` MUST
NOT invoke ``subprocess.run`` unless the caller passes
``allow_install=True`` / ``allow_update=True``. The base class enforces
the gate so subclasses cannot accidentally regress it. Subclasses that
override these methods (e.g. :class:`PylspInstaller` for the
post-install pylsp-rope inject step) MUST preserve the gate by routing
through ``super().install`` / ``super().update``.
"""

from serena.installer.basedpyright_installer import BasedpyrightInstaller
from serena.installer.clippy_installer import ClippyInstaller
from serena.installer.installer import InstalledStatus, InstallResult, LspInstaller
from serena.installer.marksman_installer import MarksmanInstaller
from serena.installer.pylsp_installer import PylspInstaller
from serena.installer.ruff_installer import RuffInstaller
from serena.installer.rust_analyzer_installer import RustAnalyzerInstaller

__all__ = [
    "BasedpyrightInstaller",
    "ClippyInstaller",
    "InstallResult",
    "InstalledStatus",
    "LspInstaller",
    "MarksmanInstaller",
    "PylspInstaller",
    "RuffInstaller",
    "RustAnalyzerInstaller",
]

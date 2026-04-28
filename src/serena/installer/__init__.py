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
* :class:`MarksmanInstaller` — first concrete subclass.

Safety: :meth:`LspInstaller.install` / :meth:`LspInstaller.update` MUST
NOT invoke ``subprocess.run`` unless the caller passes
``allow_install=True`` / ``allow_update=True``. The base class enforces
the gate so subclasses cannot accidentally regress it.
"""

from serena.installer.installer import InstalledStatus, InstallResult, LspInstaller
from serena.installer.marksman_installer import MarksmanInstaller

__all__ = [
    "InstallResult",
    "InstalledStatus",
    "LspInstaller",
    "MarksmanInstaller",
]

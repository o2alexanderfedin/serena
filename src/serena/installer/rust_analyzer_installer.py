"""v1.2 Leaf A — :class:`RustAnalyzerInstaller`.

``rust-analyzer`` is the canonical Rust LSP server (homepage:
https://rust-analyzer.github.io/). The official install path is the
``rustup`` component manager:

    rustup component add rust-analyzer

That ties the installed version to the active Rust toolchain — there is
no separately-queryable upstream version channel, so
:meth:`latest_available` returns ``None``. The version printed by
``rust-analyzer --version`` (e.g. ``rust-analyzer 1.95.0 (sha date)``)
is round-tripped verbatim from :meth:`detect_installed`.

Detection is :func:`shutil.which` + ``rust-analyzer --version``; the raw
``--version`` output is preserved so the LLM can compare across hosts.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["RustAnalyzerInstaller"]


_VERSION_TIMEOUT_S = 5.0


class RustAnalyzerInstaller(LspInstaller):
    """Install / update the ``rust-analyzer`` LSP server via ``rustup``."""

    language: ClassVar[str] = "rust"
    binary_name: ClassVar[str] = "rust-analyzer"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Always returns ``None`` for ``rust-analyzer``.

        ``rustup component`` versions track the active Rust toolchain
        rather than a standalone semver channel, so there is no useful
        "latest" to compare against. The MCP tool layer treats ``None``
        as "unknown" and falls through to the ``noop`` action when the
        binary is already installed.
        """
        return None

    def _install_command(self) -> tuple[str, ...]:
        """Return ``rustup component add rust-analyzer``.

        Cross-platform: ``rustup`` is installed via the same shell
        installer everywhere (https://rustup.rs), so no platform branching
        is required. Hosts without ``rustup`` will see the install
        attempt fail loudly via :func:`subprocess.run`'s exit code.
        """
        return ("rustup", "component", "add", "rust-analyzer")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_version(self, binary_path: str) -> str | None:
        try:
            completed = subprocess.run(  # noqa: S603 — binary_path resolved by which
                (binary_path, "--version"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_VERSION_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        out = completed.stdout.strip()
        return out or None

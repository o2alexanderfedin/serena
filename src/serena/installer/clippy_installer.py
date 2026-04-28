"""v1.2 Leaf A — :class:`ClippyInstaller`.

``clippy`` is the Rust lint server (a secondary Rust LSP shipped via
``rustup component add clippy``). The actual binary on PATH is
``cargo-clippy`` (the cargo subcommand entrypoint); ``cargo clippy
--version`` and ``cargo-clippy --version`` print the same string
(``clippy 0.1.95 (sha date)``).

Like :mod:`serena.installer.rust_analyzer_installer`, the version is
toolchain-pinned: there is no separate clippy release channel, so
:meth:`latest_available` returns ``None`` and the MCP tool falls
through to ``noop`` when the binary is already on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["ClippyInstaller"]


_VERSION_TIMEOUT_S = 5.0


class ClippyInstaller(LspInstaller):
    """Install / update the ``clippy`` Rust lint server via ``rustup``."""

    language: ClassVar[str] = "rust-clippy"
    binary_name: ClassVar[str] = "cargo-clippy"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Always returns ``None`` for clippy (toolchain-pinned, like rust-analyzer)."""
        return None

    def install_command(self) -> tuple[str, ...]:
        """Return ``rustup component add clippy``.

        Cross-platform: ``rustup`` ships everywhere via the same shell
        installer, so no platform branching is required.
        """
        return ("rustup", "component", "add", "clippy")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_version(self, binary_path: str) -> str | None:
        """Probe the version directly via ``cargo-clippy --version``.

        Both ``cargo clippy --version`` and ``cargo-clippy --version``
        print the same string. We invoke ``cargo-clippy`` directly so
        the probe does not require ``cargo`` to also be on PATH.
        """
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

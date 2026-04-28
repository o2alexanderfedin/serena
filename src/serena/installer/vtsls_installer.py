"""Stream 6 / Leaf A — :class:`VtslsInstaller`.

``vtsls`` is the TypeScript LSP server that wraps VSCode's TypeScript
extension bundled language server (homepage:
https://github.com/yioneko/vtsls). It is distributed as an npm package
(``@vtsls/language-server``) and exposes a ``vtsls`` binary entry point.

Install command (all platforms with npm): ``npm install -g @vtsls/language-server``

Detection is :func:`shutil.which` + ``vtsls --version`` (which prints a
semver string such as ``0.2.9``).

:meth:`latest_available` probes ``npm view @vtsls/language-server version``
for the upstream npm registry version. The probe is network-optional:
``npm`` must be on PATH; the call is wrapped in a timeout and returns
``None`` when npm is absent or the network is offline.

Per-platform install commands: npm is cross-platform, so the same
``npm install -g @vtsls/language-server`` command works on macOS, Linux,
and Windows. No per-platform branching is needed (unlike marksman, which
ships separate binaries).
"""

from __future__ import annotations

import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["VtslsInstaller"]


_NPM_VIEW_TIMEOUT_S = 10.0
_VERSION_TIMEOUT_S = 5.0


class VtslsInstaller(LspInstaller):
    """Install / update the ``vtsls`` TypeScript LSP server via npm."""

    language: ClassVar[str] = "typescript"
    binary_name: ClassVar[str] = "vtsls"

    #: npm package name (used for both install and version lookup).
    npm_package: ClassVar[str] = "@vtsls/language-server"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup via ``npm view @vtsls/language-server version``.

        Returns the upstream npm registry version string (e.g. ``"0.2.9"``)
        or ``None`` when npm is absent, the network is offline, or the
        command times out.
        """
        npm = shutil.which("npm")
        if npm is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                (npm, "view", self.npm_package, "version"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_NPM_VIEW_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        out = completed.stdout.strip()
        return out or None

    def _install_command(self) -> tuple[str, ...]:
        """Return ``npm install -g @vtsls/language-server``.

        npm is cross-platform so no per-platform branching is required —
        unlike marksman (Homebrew / Snap / GitHub release) or pylsp (pipx).
        The ``-g`` flag installs into the global npm prefix so the
        ``vtsls`` binary lands on PATH (typically ``/usr/local/bin/vtsls``
        on macOS/Linux or ``%APPDATA%\\npm\\vtsls.cmd`` on Windows).
        """
        return ("npm", "install", "-g", self.npm_package)

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

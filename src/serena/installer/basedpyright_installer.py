"""v1.2 Leaf A — :class:`BasedpyrightInstaller`.

``basedpyright`` is a community fork of Microsoft's Pyright with extra
static-analysis features (homepage:
https://docs.basedpyright.com/). The LSP entry point binary is
``basedpyright-langserver``; the package is shipped on PyPI and on npm,
so two install paths exist:

* ``pipx install basedpyright`` (preferred — keeps the Python LSP
  stack pipx-managed alongside ruff and pylsp).
* ``npm install -g basedpyright`` (fallback — the upstream docs list
  npm as the primary delivery channel for VS Code users).

Detection is :func:`shutil.which("basedpyright-langserver")` (the LSP
entry point) + ``basedpyright --version`` (the sibling CLI in the same
install — the langserver binary itself rejects ``--version`` because
it is wired only for stdio/IPC transport). The raw version output
(e.g. ``basedpyright 1.39.3\\nbased on pyright 1.1.409``) is
round-tripped verbatim. Only the langserver entry point is required
for o2-scalpel's MCP wiring; the CLI is best-effort for version probing
and the probe gracefully degrades to ``version=None`` when it is absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["BasedpyrightInstaller"]


_PIPX_TIMEOUT_S = 5.0
_VERSION_TIMEOUT_S = 5.0


class BasedpyrightInstaller(LspInstaller):
    """Install / update the ``basedpyright`` Python LSP server via ``pipx``."""

    language: ClassVar[str] = "python-basedpyright"
    binary_name: ClassVar[str] = "basedpyright-langserver"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        # Probe the sibling ``basedpyright`` CLI rather than the langserver
        # binary (the latter rejects ``--version``; see module docstring).
        # Look for the CLI alongside the langserver first (same pipx env);
        # fall back to PATH so non-pipx layouts (npm global) still work.
        cli = Path(path).parent / "basedpyright"
        cli_str = str(cli) if cli.exists() and os.access(cli, os.X_OK) else (
            shutil.which("basedpyright")
        )
        version = self._probe_version(cli_str) if cli_str else None
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup via ``pipx list --json`` (locally installed version).

        Same rationale as :class:`RuffInstaller.latest_available` —
        surfaces the pipx-installed version rather than querying PyPI
        so the probe stays cheap and offline-tolerant. Returns ``None``
        when pipx is missing or basedpyright is not pipx-managed.
        """
        pipx = shutil.which("pipx")
        if pipx is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                (pipx, "list", "--json"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_PIPX_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        return _extract_pipx_package_version(completed.stdout, "basedpyright")

    def install_command(self) -> tuple[str, ...]:
        """Return ``pipx install basedpyright`` (preferred path).

        Cross-platform; pipx is the recommended Python user-binary
        installer everywhere. The npm fallback (``npm install -g
        basedpyright``) is documented in the module docstring but not
        wired here — pipx keeps the Python LSP stack consistent.
        """
        return ("pipx", "install", "basedpyright")

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


def _extract_pipx_package_version(stdout: str, package: str) -> str | None:
    """Extract a package's installed version from ``pipx list --json``.

    ``pipx list --json`` returns ``{"venvs": {package: {"metadata": {
    "main_package": {"package_version": "X.Y.Z"}}}}}``. Returns ``None``
    when the JSON cannot be parsed or the package is not installed.
    """
    import json

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    venvs = payload.get("venvs")
    if not isinstance(venvs, dict):
        return None
    venv = venvs.get(package)
    if not isinstance(venv, dict):
        return None
    metadata = venv.get("metadata")
    if not isinstance(metadata, dict):
        return None
    main_package = metadata.get("main_package")
    if not isinstance(main_package, dict):
        return None
    version = main_package.get("package_version")
    if isinstance(version, str) and version:
        return version
    return None

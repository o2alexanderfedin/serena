"""v1.2 Leaf A — :class:`RuffInstaller`.

``ruff`` is the canonical Python linter+formatter LSP (homepage:
https://docs.astral.sh/ruff/). It is shipped as a single static binary
on PyPI; the recommended user install is via ``pipx`` so the binary
goes onto PATH in an isolated environment:

    pipx install ruff

A ``cargo install ruff`` fallback also works (ruff is a Rust binary)
but ``pipx`` is preferred because it integrates with the Python
ecosystem the rest of the o2-scalpel Python LSP stack already uses.

Detection is :func:`shutil.which` + ``ruff --version`` (e.g.
``ruff 0.14.6``); the raw output is round-tripped verbatim.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["RuffInstaller"]


_PIPX_TIMEOUT_S = 5.0
_VERSION_TIMEOUT_S = 5.0


class RuffInstaller(LspInstaller):
    """Install / update the ``ruff`` Python lint+format LSP server via ``pipx``."""

    language: ClassVar[str] = "python-ruff"
    binary_name: ClassVar[str] = "ruff"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup via ``pipx list --json`` (locally installed version).

        We surface the *installed* pipx version rather than the upstream
        PyPI version because the registry probe needs to be cheap +
        offline-tolerant (``pip index versions`` requires network and
        prints to stderr on offline hosts). Returns ``None`` when pipx
        is not on PATH or when ruff is not pipx-managed.
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
        return _extract_pipx_package_version(completed.stdout, "ruff")

    def _install_command(self) -> tuple[str, ...]:
        """Return ``pipx install ruff``.

        Cross-platform: pipx is the recommended Python user-binary
        installer everywhere. Hosts without pipx will see the install
        attempt fail loudly via :func:`subprocess.run`'s exit code.
        Cargo fallback (``cargo install ruff``) is available manually.
        """
        return ("pipx", "install", "ruff")

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

"""v1.1.1 Leaf 03 C2 — :class:`MarksmanInstaller`.

The first concrete :class:`LspInstaller`. ``marksman`` is the
canonical markdown LSP server (homepage:
https://github.com/artempyanykh/marksman). It ships pre-built binaries
for macOS, Linux, and Windows and is packaged on Homebrew + Snap.

Detection is :func:`shutil.which` + ``marksman --version`` (which prints
the build date, e.g. ``2026-02-08`` — NOT semver). The version string
is round-tripped verbatim so the LLM can compare against
:meth:`latest_available`'s output (also a date for marksman).

Per-platform install commands:

* macOS  → ``brew install marksman``
* Linux  → ``snap install marksman``
* other  → :exc:`NotImplementedError` (the user can still install
  manually from a GitHub release; we don't pretend to know the right
  command on platforms we haven't tested).

:meth:`latest_available` queries ``brew info --json marksman`` on macOS
and returns ``None`` everywhere else (and on offline / brew-missing
hosts) — network is optional per the ABC contract.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["MarksmanInstaller"]


_BREW_TIMEOUT_S = 5.0
_VERSION_TIMEOUT_S = 5.0


class MarksmanInstaller(LspInstaller):
    """Install / update the ``marksman`` markdown LSP server."""

    language: ClassVar[str] = "markdown"
    binary_name: ClassVar[str] = "marksman"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup of the upstream stable version.

        macOS: parse ``brew info --json=v2 marksman``. Other platforms
        return ``None`` (Snap doesn't expose a comparable JSON API and
        the GitHub-releases path is deferred to v1.2 once we have a
        second consumer).
        """
        if platform.system() != "Darwin":
            return None
        brew = shutil.which("brew")
        if brew is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                (brew, "info", "--json=v2", self.binary_name),
                capture_output=True,
                text=True,
                check=False,
                timeout=_BREW_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return None
        return _extract_brew_stable_version(payload, self.binary_name)

    def install_command(self) -> tuple[str, ...]:
        system = platform.system()
        if system == "Darwin":
            return ("brew", "install", self.binary_name)
        if system == "Linux":
            return ("snap", "install", self.binary_name)
        raise NotImplementedError(
            f"No install command registered for platform {system!r}; "
            f"install marksman manually from "
            f"https://github.com/artempyanykh/marksman/releases.",
        )

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


def _extract_brew_stable_version(
    payload: object,
    formula_name: str,
) -> str | None:
    """Pull ``formulae[].versions.stable`` (or top-level ``versions.stable``).

    ``brew info --json=v2`` wraps formulae in a ``{"formulae": [...]}``
    envelope; older callers see ``[{...}]`` straight from ``--json``.
    Both shapes are accepted so the extractor stays compatible across
    brew versions.
    """
    if isinstance(payload, dict):
        formulae = payload.get("formulae") or []
    elif isinstance(payload, list):
        formulae = payload
    else:
        return None
    if not isinstance(formulae, list):
        return None
    for entry in formulae:
        if not isinstance(entry, dict):
            continue
        if entry.get("name") != formula_name:
            continue
        versions = entry.get("versions")
        if not isinstance(versions, dict):
            continue
        stable = versions.get("stable")
        if isinstance(stable, str) and stable:
            return stable
    return None

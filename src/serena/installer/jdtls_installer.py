"""Stream 6 / Leaf D — :class:`JdtlsInstaller`.

``jdtls`` is the Eclipse JDT Language Server — the canonical Java LSP
maintained by the Eclipse Foundation
(homepage: https://github.com/eclipse-jdtls/eclipse.jdt.ls). It is
available through package managers on macOS and Linux.

Per-platform install commands:

* macOS  → ``brew install jdtls`` (Homebrew cask; ships the wrapper script)
* Linux  → ``snap install jdtls --classic``
* other  → :exc:`NotImplementedError` (the user can still install manually
  from https://github.com/eclipse-jdtls/eclipse.jdt.ls/releases; we don't
  pretend to know the right command on platforms we haven't tested).

Detection is :func:`shutil.which` + ``jdtls --version`` (which prints a
version line such as ``jdtls 1.38.0``).

:meth:`latest_available` probes ``brew info --json=v2 jdtls`` on macOS to
extract the stable jdtls version. The probe is network-optional: ``brew``
must be reachable and the call is wrapped in a timeout; returns ``None``
when brew is absent or the network is offline.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["JdtlsInstaller"]


_BREW_TIMEOUT_S = 5.0
_VERSION_TIMEOUT_S = 5.0

# jdtls version output: "jdtls 1.38.0" or similar.
_VERSION_RE = re.compile(r"jdtls\s+([\d.]+(?:-\S+)?)")


class JdtlsInstaller(LspInstaller):
    """Install / update the ``jdtls`` Java LSP server via the system package manager."""

    language: ClassVar[str] = "java"
    binary_name: ClassVar[str] = "jdtls"

    #: Homebrew formula that ships jdtls on macOS.
    brew_formula: ClassVar[str] = "jdtls"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup of the upstream stable jdtls version.

        macOS: parse ``brew info --json=v2 jdtls`` to extract the stable
        version. Other platforms return ``None`` (Snap doesn't expose a
        comparable JSON API).
        """
        if platform.system() != "Darwin":
            return None
        brew = shutil.which("brew")
        if brew is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                (brew, "info", "--json=v2", self.brew_formula),
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
        return _extract_brew_stable_version(payload, self.brew_formula)

    def _install_command(self) -> tuple[str, ...]:
        system = platform.system()
        if system == "Darwin":
            return ("brew", "install", self.brew_formula)
        if system == "Linux":
            return ("snap", "install", "jdtls", "--classic")
        raise NotImplementedError(
            f"No install command registered for platform {system!r}; "
            f"install jdtls manually from "
            f"https://github.com/eclipse-jdtls/eclipse.jdt.ls/releases.",
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
        # jdtls may return non-zero for --version on some distributions;
        # we still try to parse the output.
        out = (completed.stdout or completed.stderr or "").strip()
        if not out:
            return None
        match = _VERSION_RE.search(out)
        if match:
            return match.group(1)
        return out


def _extract_brew_stable_version(
    payload: object,
    formula_name: str,
) -> str | None:
    """Pull ``formulae[].versions.stable`` from a ``brew info --json=v2`` payload.

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

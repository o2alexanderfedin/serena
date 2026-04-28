"""Stream 6 / Leaf C — :class:`ClangdInstaller`.

``clangd`` is the canonical C/C++ language server maintained by the LLVM
project (homepage: https://clangd.llvm.org). It is distributed as part of
the LLVM toolchain and available through package managers on all platforms.

Per-platform install commands:

* macOS  → ``brew install llvm`` (clangd ships as part of llvm) or
           ``brew install clangd`` (standalone formula, if available)
* Linux  → ``snap install clangd --classic``
* other  → :exc:`NotImplementedError` (the user can still install manually
  from https://github.com/clangd/clangd/releases; we don't pretend to know
  the right command on platforms we haven't tested).

Detection is :func:`shutil.which` + ``clangd --version`` (which prints a
version line such as ``clangd version 18.1.3``).

:meth:`latest_available` probes ``brew info --json=v2 llvm`` on macOS to
extract the stable llvm version (clangd version tracks llvm). The probe is
network-optional: ``brew`` must be reachable and the call is wrapped in a
timeout; returns ``None`` when brew is absent or the network is offline.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["ClangdInstaller"]


_BREW_TIMEOUT_S = 5.0
_VERSION_TIMEOUT_S = 5.0

# clangd version output: "clangd version 18.1.3" or "Ubuntu clangd version 14.0.0-1ubuntu1"
_VERSION_RE = re.compile(r"clangd\s+version\s+([\d.]+(?:-\S+)?)")


class ClangdInstaller(LspInstaller):
    """Install / update the ``clangd`` C/C++ LSP server via the system package manager."""

    language: ClassVar[str] = "cpp"
    binary_name: ClassVar[str] = "clangd"

    #: Homebrew formula that ships clangd on macOS.
    brew_formula: ClassVar[str] = "llvm"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup of the upstream stable clangd/llvm version.

        macOS: parse ``brew info --json=v2 llvm`` to extract the stable
        llvm version (clangd version tracks llvm). Other platforms return
        ``None`` (Snap doesn't expose a comparable JSON API and the
        GitHub-releases path is deferred until a second consumer needs it).
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
            return ("snap", "install", "clangd", "--classic")
        raise NotImplementedError(
            f"No install command registered for platform {system!r}; "
            f"install clangd manually from "
            f"https://github.com/clangd/clangd/releases.",
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
        # clangd prints version to both stdout and stderr depending on version;
        # try stdout first, then stderr.
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

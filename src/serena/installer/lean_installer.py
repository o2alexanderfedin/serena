"""Stream 6 / Leaf E — :class:`LeanInstaller`.

``lean`` is the Lean 4 compiler and theorem prover
(homepage: https://leanprover.github.io/lean4/). Its LSP server is
built-in — invoking ``lean --server`` starts the language server over
stdio. There is no separate LSP binary to install.

The recommended Lean 4 installation path is via **elan**
(https://github.com/leanprover/elan), the Lean toolchain manager
(analogous to rustup). elan manages multiple Lean versions, handles
project-local toolchain pins (``lean-toolchain`` file), and places
``lean`` on PATH.

Bootstrap (first install):
  ``curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh``
  then ``elan toolchain install stable``

Subsequent updates:
  ``elan update`` (updates all installed toolchains)

Detection is :func:`shutil.which` + ``lean --version`` (which prints a
version line such as ``Lean (version 4.14.0, ...))``).

:meth:`latest_available` probes ``elan toolchain list`` to find the
installed stable toolchain version. Returns ``None`` when elan is absent
or the output cannot be parsed — network is not required.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["LeanInstaller"]


_VERSION_TIMEOUT_S = 5.0
_ELAN_TIMEOUT_S = 5.0

# ``lean --version`` prints: "Lean (version 4.14.0, commit abc1234, Release)"
_VERSION_RE = re.compile(r"version\s+([\d.]+(?:-\S+)?)")

# ``elan toolchain list`` prints one toolchain per line, e.g.:
#   leanprover/lean4:stable (default)
#   leanprover/lean4:v4.14.0
_ELAN_STABLE_RE = re.compile(r"lean4:v([\d.]+)")


class LeanInstaller(LspInstaller):
    """Install / update the Lean 4 toolchain via elan."""

    language: ClassVar[str] = "lean"
    binary_name: ClassVar[str] = "lean"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup of the installed stable Lean toolchain version.

        Queries ``elan toolchain list`` to find the latest installed stable
        version.  This does not require a network call — elan reports
        locally-installed toolchains from its toolchain cache.

        Returns ``None`` when elan is absent, the output cannot be parsed,
        or no stable toolchain is installed.
        """
        elan = shutil.which("elan")
        if elan is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                (elan, "toolchain", "list"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_ELAN_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        return _extract_elan_stable_version(completed.stdout)

    def _install_command(self) -> tuple[str, ...]:
        """Return the elan toolchain install command.

        elan is cross-platform (macOS, Linux, Windows). The bootstrap
        step (curl-then-bash) is a one-time operation that installs elan
        itself; subsequent installs/updates go through ``elan toolchain
        install stable``.

        If elan is already present on PATH, we install the stable Lean
        toolchain.  If elan is not present, we raise ``NotImplementedError``
        to surface the bootstrap requirement to the user — the curl-then-bash
        bootstrap is a security-sensitive one-liner and we do not want to
        auto-exec it silently.
        """
        elan = shutil.which("elan")
        if elan is not None:
            # elan is installed — install/upgrade the stable toolchain.
            return (elan, "toolchain", "install", "stable")
        # elan is absent. Surface the bootstrap instructions rather than
        # silently running curl | sh.
        system = platform.system()
        raise NotImplementedError(
            f"elan (the Lean toolchain manager) is not installed on this "
            f"{system} host. To bootstrap Lean 4:\n"
            f"  curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh\n"
            f"After bootstrapping, re-run this tool to install the stable toolchain.\n"
            f"Docs: https://github.com/leanprover/elan"
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
        out = (completed.stdout or completed.stderr or "").strip()
        if not out:
            return None
        match = _VERSION_RE.search(out)
        if match:
            return match.group(1)
        return out


def _extract_elan_stable_version(elan_output: str) -> str | None:
    """Extract the latest concrete stable version from ``elan toolchain list`` output.

    Lines look like::

        leanprover/lean4:stable (default)
        leanprover/lean4:v4.14.0

    We pick the highest ``v<semver>`` line (not the symbolic ``stable``
    alias) so the version string is comparable.
    """
    versions: list[str] = []
    for line in elan_output.splitlines():
        match = _ELAN_STABLE_RE.search(line)
        if match:
            versions.append(match.group(1))
    if not versions:
        return None
    # Return the lexicographically-last version (good enough for semver
    # strings where major.minor.patch are all present).
    return sorted(versions)[-1]

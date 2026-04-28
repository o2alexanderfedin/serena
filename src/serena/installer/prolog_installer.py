"""Stream 6 / Leaf G — :class:`PrologInstaller`.

Prolog LSP server: the ``lsp_server`` SWI-Prolog pack by James Cash
(https://github.com/jamesnvc/lsp_server).

The pack installs inside SWI-Prolog's package system; there is no separate
binary — the server is launched by the ``swipl`` runtime.  Install:

  ``swipl -g "pack_install(lsp_server)" -t halt``

Or interactively from the SWI-Prolog REPL:

  ``?- pack_install(lsp_server).``

Requires SWI-Prolog 8.1.5 or newer (earlier versions lack the
``find_references`` predicate used by the pack).

**Detection strategy:**

The installer checks for the ``swipl`` binary on PATH (required for the
runtime) and probes ``swipl --version`` for the version string.  The pack
version is detected by querying ``swipl -g "pack_property(lsp_server, version(V))"``
— this is a fast, offline query against SWI-Prolog's installed pack database.

**Install command:**

The install command is ``swipl -g "pack_install(lsp_server, [interactive(false)])" -t halt``,
which installs or upgrades the pack non-interactively.

:meth:`latest_available` returns ``None`` — the pack registry does not expose
a stable "latest version" API without a live network call to SWI-Prolog's
pack server.  The installer detects the locally installed version and flags
for install/noop, but never for update (update is left to the user).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["PrologInstaller"]


_VERSION_TIMEOUT_S = 5.0
_PACK_TIMEOUT_S = 8.0

# ``swipl --version`` prints: "SWI-Prolog version 9.2.3 for x86_64-darwin"
_SWIPL_VERSION_RE = re.compile(r"version\s+([\d.]+(?:-\S+)?)")

# Pack presence query: succeeds (exits 0) when lsp_server is installed.
# Fail (exit non-zero) when the pack is absent.
_PACK_QUERY = "pack_property(lsp_server, version(_))"
_PACK_VERSION_PREFIX = "pack_property(lsp_server, version("


class PrologInstaller(LspInstaller):
    """Install / detect the SWI-Prolog ``lsp_server`` pack."""

    language: ClassVar[str] = "prolog"
    binary_name: ClassVar[str] = "swipl"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        swipl_version = self._probe_swipl_version(path)
        pack_version = self._probe_pack_version(path)
        # Report present only if both swipl and the lsp_server pack are installed.
        if pack_version is None:
            return InstalledStatus(present=False, version=swipl_version, path=path)
        # Report the combined version as "swipl-<ver>/pack-<pack_ver>" for clarity.
        combined = f"swipl-{swipl_version or '?'}/pack-{pack_version}"
        return InstalledStatus(present=True, version=combined, path=path)

    def latest_available(self) -> str | None:
        """Returns ``None``: the SWI-Prolog pack registry requires a live
        network call to determine the latest version.  We leave update
        detection to the user (``swipl -g "pack_upgrade(lsp_server)" -t halt``).
        """
        return None

    def _install_command(self) -> tuple[str, ...]:
        """Return the pack install command.

        If ``swipl`` is absent, raises ``NotImplementedError`` pointing the
        user to the SWI-Prolog download page.  If ``swipl`` is present but
        the pack is not installed, returns the pack_install command.
        """
        swipl = shutil.which(self.binary_name)
        if swipl is None:
            import platform
            system = platform.system()
            raise NotImplementedError(
                f"SWI-Prolog (swipl) is not installed on this {system} host.\n"
                f"Install SWI-Prolog first, then re-run this tool:\n"
                f"  macOS:  brew install swi-prolog\n"
                f"  Debian: apt-get install swi-prolog\n"
                f"  Windows / source: https://www.swi-prolog.org/Download.html\n"
                f"\nAfter installing SWI-Prolog, the lsp_server pack will be "
                f"installed automatically by running this tool again."
            )
        return (
            swipl,
            "-g", "pack_install(lsp_server, [interactive(false)])",
            "-t", "halt",
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_swipl_version(self, binary_path: str) -> str | None:
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
        match = _SWIPL_VERSION_RE.search(out)
        if match:
            return match.group(1)
        return out

    def _probe_pack_version(self, binary_path: str) -> str | None:
        """Query the installed lsp_server pack version via swipl goal."""
        version_goal = (
            "pack_property(lsp_server, version(V)), "
            "format(atom(S), '~w', [V]), "
            "write(S), nl"
        )
        try:
            completed = subprocess.run(  # noqa: S603
                (binary_path, "-g", version_goal, "-t", "halt"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_PACK_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        out = (completed.stdout or "").strip()
        # The goal writes the version atom (e.g. "0.9.5") then halts.
        if out and re.match(r"[\d.]+", out):
            return out
        return None

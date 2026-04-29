"""v1.4.1 Leaf B — :class:`Smt2Installer` (dolmenls GitHub-Releases downloader).

dolmenls (https://github.com/Gbury/dolmen, the Dolmen monorepo's LSP server)
is the SMT-LIB 2 language server backend selected for the o2-scalpel SMT2
plugin. Upstream ships pre-built single-file binaries for Linux, macOS, and
Windows on every release; we pin to ``v0.10`` (the latest as of 2026-04-28).

Architectural choice — GitHub Releases over opam (per v1.4.1 plan):
  Most o2-scalpel users have no OCaml toolchain. opam (the official upstream
  channel) would force a heavy install for a single binary. The pre-built
  asset path slots into the existing :class:`LspInstaller` ABC without
  introducing a 5th package-manager channel (vs. brew/cargo/pipx/npm/elan).

Install mechanism:
  :meth:`_install_command` returns ``("sh", "-c", "<chain>")`` where the
  chain runs ``mkdir -p ~/.local/bin && curl -fL ... && chmod +x ...``.
  This fits the single-argv contract of :meth:`LspInstaller.install` while
  doing the multi-step download + permission set in one shot. The
  user audits the full chain via the dry-run envelope before approving.

Detection: :func:`shutil.which` for ``dolmenls`` + best-effort ``--version``
probe (dolmenls v0.10 may not implement ``--version``; we tolerate that
and surface ``present=True`` with ``version=None``).

Latest-available: queries the GitHub Releases API
(``https://api.github.com/repos/Gbury/dolmen/releases/latest``); offline-
safe — returns ``None`` rather than raising.
"""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = [
    "Smt2Installer",
    "_DEFAULT_INSTALL_DIR",
    "_GITHUB_API_LATEST",
    "_PINNED_VERSION",
    "_platform_asset_name",
]


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

#: Dolmen release pinned by this installer. Bump on a quarterly cadence;
#: the drift CI gate would surface staleness.
_PINNED_VERSION = "v0.10"

#: Per-version release-asset URL prefix; expand with ``{asset_name}``.
_RELEASE_BASE = "https://github.com/Gbury/dolmen/releases/download"

#: GitHub API endpoint that returns the latest release JSON. Used by
#: :meth:`latest_available`; offline-safe.
_GITHUB_API_LATEST = "https://api.github.com/repos/Gbury/dolmen/releases/latest"

#: Where the binary lands on the user's host. ``~/.local/bin`` is XDG-friendly,
#: user-writable, and on PATH for most shells (Bash/Zsh ``~/.profile`` typically
#: prepends it). Other installers (brew/cargo/elan) manage their own paths.
_DEFAULT_INSTALL_DIR = Path.home() / ".local" / "bin"

#: Network timeout for GitHub API queries (seconds).
_API_TIMEOUT_S = 5.0

#: ``--version`` probe timeout (seconds).
_VERSION_TIMEOUT_S = 5.0

#: dolmenls ``--version`` may print ``dolmenls v0.10`` or similar; capture the
#: first ``vN.M`` or ``N.M`` token as the version string.
_VERSION_RE = re.compile(r"v?(\d+\.\d+(?:\.\d+)?(?:-\S+)?)")


# -----------------------------------------------------------------------------
# Platform asset selection
# -----------------------------------------------------------------------------


def _platform_asset_name() -> str:
    """Return the GitHub-Releases asset name for the current platform.

    Upstream ships ``dolmenls-{linux,macos,windows}-amd64`` (and ``.exe``
    for Windows). ARM hosts (Apple Silicon / Linux ARM) currently fall back
    to amd64 via Rosetta-2 on macOS; native arm64 assets do not exist as of
    v0.10. This is documented for forward-compatibility — bump the asset
    map when upstream ships native arm64.
    """

    system = platform.system()
    if system == "Darwin":
        return "dolmenls-macos-amd64"
    if system == "Linux":
        return "dolmenls-linux-amd64"
    if system == "Windows":
        return "dolmenls-windows-amd64.exe"
    raise NotImplementedError(
        f"dolmenls has no pre-built binary for platform {system!r}. "
        f"Supported: Darwin, Linux, Windows. Build from source via "
        f"`opam install dolmen_lsp`."
    )


# -----------------------------------------------------------------------------
# Smt2Installer
# -----------------------------------------------------------------------------


class Smt2Installer(LspInstaller):
    """Install / update the ``dolmenls`` LSP binary from GitHub Releases."""

    language: ClassVar[str] = "smt2"
    binary_name: ClassVar[str] = "dolmenls"

    # ------------------------------------------------------------------
    # detect_installed
    # ------------------------------------------------------------------

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    # ------------------------------------------------------------------
    # latest_available
    # ------------------------------------------------------------------

    def latest_available(self) -> str | None:
        """Best-effort lookup of the latest dolmen release tag.

        Queries the GitHub Releases API. Network is optional — any error
        (DNS, timeout, 5xx, malformed JSON, missing ``tag_name`` field)
        returns ``None`` rather than raising, matching the offline-safe
        contract on :class:`LspInstaller`.
        """

        try:
            with urllib.request.urlopen(  # noqa: S310 — fixed https endpoint, no user input
                _GITHUB_API_LATEST, timeout=_API_TIMEOUT_S
            ) as response:
                payload = response.read()
        except (urllib.error.URLError, OSError, TimeoutError):
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return None
        tag = data.get("tag_name") if isinstance(data, dict) else None
        return tag if isinstance(tag, str) else None

    # ------------------------------------------------------------------
    # _install_command
    # ------------------------------------------------------------------

    def _install_command(self) -> tuple[str, ...]:
        """Return a single ``sh -c`` chain that downloads + chmods dolmenls.

        The chain is auditable verbatim via the install-result envelope
        (``InstallResult.command_run``), so the LLM can review the
        download URL and target path before approving.
        """

        system = platform.system()
        if system == "Windows":
            # Windows lacks POSIX sh + curl by default; bootstrap via
            # ``opam`` or download the asset manually. Surface a clear
            # error rather than silently emitting a broken cmd.exe chain.
            raise NotImplementedError(
                "Automatic dolmenls install on Windows is not yet supported. "
                "Download dolmenls-windows-amd64.exe manually from "
                f"{_RELEASE_BASE}/{_PINNED_VERSION}/dolmenls-windows-amd64.exe "
                "and place it on PATH, or install via opam: "
                "`opam install dolmen_lsp`."
            )
        asset = _platform_asset_name()
        url = f"{_RELEASE_BASE}/{_PINNED_VERSION}/{asset}"
        target = _DEFAULT_INSTALL_DIR / "dolmenls"
        # NOTE: the chain uses ``-fL`` to fail on HTTP errors and follow
        # redirects (GitHub Releases serves a 302 to S3-backed CDN).
        chain = (
            f"mkdir -p {target.parent} && "
            f"curl -fL -o {target} {url} && "
            f"chmod +x {target}"
        )
        return ("sh", "-c", chain)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_version(self, binary_path: str) -> str | None:
        """Best-effort ``dolmenls --version`` probe.

        dolmenls v0.10's CLI surface is undocumented; ``--version`` may not
        be implemented. On non-zero exit we tolerate (return ``None``)
        rather than treat the binary as missing — :func:`shutil.which`
        already established it's there.
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
        out = (completed.stdout or completed.stderr or "").strip()
        if not out:
            return None
        match = _VERSION_RE.search(out)
        if match:
            return match.group(1)
        return out

"""Stream 6 / Leaf I — :class:`CsharpLsInstaller`.

``csharp-ls`` is a Roslyn-based C# language server
(homepage: https://github.com/razzmatazz/csharp-language-server).
It is distributed as a .NET global tool and is simpler to install than
OmniSharp (no tarball + Mono dance) — a single ``dotnet`` invocation puts
the binary on PATH.

Install command (cross-platform):
  ``dotnet tool install --global csharp-ls``

Update command:
  ``dotnet tool update --global csharp-ls``

Detection is :func:`shutil.which` + ``csharp-ls --version`` (which prints
a version line such as ``0.14.0+e5a1b23``).

:meth:`latest_available` probes ``dotnet tool search csharp-ls`` to extract
the latest NuGet package version.  The probe is network-optional: ``dotnet``
must be reachable; returns ``None`` when dotnet is absent or the call fails.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["CsharpLsInstaller"]


_DOTNET_TIMEOUT_S = 10.0
_VERSION_TIMEOUT_S = 5.0

# ``csharp-ls --version`` typically prints: "0.14.0+e5a1b23" or "0.14.0"
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:\+\S+)?)")

# ``dotnet tool search csharp-ls`` output lines look like:
#   Package ID          Latest Version   Authors  ...
#   csharp-ls           0.14.0           ...
# We look for a line that starts with the exact package id "csharp-ls".
_SEARCH_VERSION_RE = re.compile(r"^csharp-ls\s+([\d.]+)", re.MULTILINE | re.IGNORECASE)


class CsharpLsInstaller(LspInstaller):
    """Install / update the ``csharp-ls`` C# LSP server via dotnet tool."""

    language: ClassVar[str] = "csharp"
    binary_name: ClassVar[str] = "csharp-ls"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup of the latest published csharp-ls version.

        Queries ``dotnet tool search csharp-ls`` to find the latest published
        NuGet package version.  This requires a network call; returns ``None``
        when dotnet is absent, the network is offline, or the output cannot
        be parsed.
        """
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                (dotnet, "tool", "search", "csharp-ls"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_DOTNET_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        return _extract_search_version(completed.stdout)

    def _install_command(self) -> tuple[str, ...]:
        """Return the dotnet tool install command.

        ``dotnet tool install --global csharp-ls`` is cross-platform:
        macOS, Linux, and Windows all use the same command.  The installed
        binary lands in the per-user dotnet tools directory (~/.dotnet/tools
        on Unix) which ``dotnet`` adds to PATH automatically when it is
        configured (``~/.dotnet/tools`` must be in PATH for the binary to be
        found via ``shutil.which``).
        """
        dotnet = shutil.which("dotnet")
        if dotnet is None:
            raise NotImplementedError(
                "The .NET SDK / Runtime is not installed on this host. "
                "Install .NET 6 or later from https://dot.net and then re-run this tool.\n"
                "After installing .NET, run:\n"
                "  dotnet tool install --global csharp-ls\n"
                "and ensure ~/.dotnet/tools is on your PATH."
            )
        return (dotnet, "tool", "install", "--global", "csharp-ls")

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
        # csharp-ls may return non-zero for --version on some setups;
        # we still try to parse the output.
        out = (completed.stdout or completed.stderr or "").strip()
        if not out:
            return None
        match = _VERSION_RE.search(out)
        if match:
            return match.group(1)
        return out


def _extract_search_version(search_output: str) -> str | None:
    """Parse the latest version from ``dotnet tool search csharp-ls`` output.

    The output looks like::

        Package ID      Latest Version  Authors               ...
        ---------------------------------------------------------------
        csharp-ls       0.14.0          razzmatazz            ...

    We scan for a line starting with ``csharp-ls`` (the exact package ID)
    and extract the version token that follows.
    """
    match = _SEARCH_VERSION_RE.search(search_output)
    if match:
        return match.group(1)
    return None

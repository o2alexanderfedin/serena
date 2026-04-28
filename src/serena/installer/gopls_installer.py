"""Stream 6 / Leaf B — :class:`GoplsInstaller`.

``gopls`` is the official Go language server maintained by the Go team
(homepage: https://github.com/golang/tools/tree/master/gopls). It is
distributed as a Go module and installed via the standard Go toolchain:

Install command: ``go install golang.org/x/tools/gopls@latest``

This places the ``gopls`` binary in the Go bin directory (typically
``$GOPATH/bin`` or ``$HOME/go/bin``), which should be on PATH.

Detection is :func:`shutil.which` + ``gopls version`` (which prints a
version line such as ``golang.org/x/tools/gopls v0.16.1``).

:meth:`latest_available` probes the Go module proxy at
``https://proxy.golang.org/golang.org/x/tools/gopls/@latest`` for the
upstream module version. The probe is network-optional: ``curl`` or the
``go`` binary (via ``go list -m -versions``) must be reachable; the call
is wrapped in a timeout and returns ``None`` when the Go toolchain is
absent or the network is offline.

Per-platform install commands: the Go toolchain is cross-platform, so
the same ``go install golang.org/x/tools/gopls@latest`` command works on
macOS, Linux, and Windows. No per-platform branching is needed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstalledStatus, LspInstaller

__all__ = ["GoplsInstaller"]


_GO_LIST_TIMEOUT_S = 15.0
_VERSION_TIMEOUT_S = 5.0

# gopls version output: "golang.org/x/tools/gopls v0.16.1"
_VERSION_RE = re.compile(r"gopls\s+v?([\d.]+(?:-\w+)?)")


class GoplsInstaller(LspInstaller):
    """Install / update the ``gopls`` Go LSP server via the Go toolchain."""

    language: ClassVar[str] = "go"
    binary_name: ClassVar[str] = "gopls"

    #: Go module path for the gopls tool.
    module_path: ClassVar[str] = "golang.org/x/tools/gopls"

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup via ``go list -m -versions golang.org/x/tools/gopls``.

        Returns the latest version string (e.g. ``"v0.16.1"``) or ``None``
        when the Go toolchain is absent, the network is offline, or the
        command times out.

        Uses ``go list -m -json golang.org/x/tools/gopls@latest`` which
        queries the module proxy and returns structured JSON.
        """
        go = shutil.which("go")
        if go is None:
            return None
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                (go, "list", "-m", "-json", f"{self.module_path}@latest"),
                capture_output=True,
                text=True,
                check=False,
                timeout=_GO_LIST_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        # Parse the JSON output: {"Path":"...", "Version":"v0.16.1", ...}
        import json as _json

        try:
            data = _json.loads(completed.stdout)
            version = data.get("Version")
            return version if version else None
        except (_json.JSONDecodeError, AttributeError):
            return None

    def _install_command(self) -> tuple[str, ...]:
        """Return ``go install golang.org/x/tools/gopls@latest``.

        The Go toolchain is cross-platform so no per-platform branching is
        required — unlike marksman (Homebrew / Snap / GitHub release) or
        pylsp (pipx). The binary lands in ``$GOPATH/bin`` (typically
        ``$HOME/go/bin``), which must be on PATH for gopls to be callable.
        """
        return ("go", "install", f"{self.module_path}@latest")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _probe_version(self, binary_path: str) -> str | None:
        try:
            completed = subprocess.run(  # noqa: S603 — binary_path resolved by which
                (binary_path, "version"),
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
        if not out:
            return None
        # Parse "golang.org/x/tools/gopls v0.16.1" → "v0.16.1"
        match = _VERSION_RE.search(out)
        if match:
            return f"v{match.group(1)}"
        return out

"""v1.2 Leaf A — :class:`PylspInstaller`.

``pylsp`` (the python-lsp-server fork of the older ``python-language-server``)
is the canonical community Python LSP (homepage:
https://github.com/python-lsp/python-lsp-server). The o2-scalpel
Python LSP stack drives pylsp WITH the ``pylsp-rope`` plugin (Stage 1E
adapter notes) so the install flow has TWO steps:

1. ``pipx install python-lsp-server``  — installs the ``pylsp`` entry point.
2. ``pipx inject python-lsp-server pylsp-rope`` — injects the rope
   refactoring plugin into the same pipx env so pylsp picks it up.

Skipping step 2 means refactor capabilities (rope.refactor.extract,
rope.refactor.inline, rope.refactor.rename — see
``scalpel_primitives._EXECUTE_COMMAND_WHITELIST``) silently degrade to
text-only navigation.

Both steps are gated by the same ``allow_install=True`` /
``allow_update=True`` flag the base class enforces — there is NO way
to invoke either subprocess command without explicit consent.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import ClassVar

from serena.installer.installer import InstallResult, InstalledStatus, LspInstaller

__all__ = ["PylspInstaller"]


_PIPX_TIMEOUT_S = 5.0
_VERSION_TIMEOUT_S = 5.0


class PylspInstaller(LspInstaller):
    """Install / update the ``pylsp`` Python LSP server (with pylsp-rope)."""

    language: ClassVar[str] = "python"
    binary_name: ClassVar[str] = "pylsp"

    #: Post-install plugin injection (rope refactoring backend).
    inject_command: ClassVar[tuple[str, ...]] = (
        "pipx", "inject", "python-lsp-server", "pylsp-rope",
    )

    def detect_installed(self) -> InstalledStatus:
        path = shutil.which(self.binary_name)
        if path is None:
            return InstalledStatus(present=False, version=None, path=None)
        version = self._probe_version(path)
        return InstalledStatus(present=True, version=version, path=path)

    def latest_available(self) -> str | None:
        """Best-effort lookup via ``pipx list --json`` for python-lsp-server.

        Same rationale as :class:`RuffInstaller.latest_available`: the
        pipx-installed version is cheap + offline-tolerant; PyPI lookup
        is intentionally skipped to keep the probe network-optional.
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
        return _extract_pipx_package_version(completed.stdout, "python-lsp-server")

    def _install_command(self) -> tuple[str, ...]:
        """Return ``pipx install python-lsp-server``.

        The pylsp-rope plugin injection runs as a separate post-step
        inside :meth:`install` / :meth:`update`. ``_install_command``
        only exposes the primary install argv so the dry-run preview
        stays focused on the headline action; the inject argv lives in
        :attr:`inject_command` and is surfaced explicitly by callers
        that care (test suite + the v1.2 MCP tool report).
        """
        return ("pipx", "install", "python-lsp-server")

    # ------------------------------------------------------------------
    # Safety-gated install/update with post-install pylsp-rope inject.
    # ------------------------------------------------------------------

    def install(self, *, allow_install: bool = False) -> InstallResult:
        """Install pylsp + inject pylsp-rope.

        The base ``LspInstaller.install`` enforces the safety gate
        (``allow_install=False`` returns dry-run, never invokes
        :func:`subprocess.run`). When the gate is open AND the primary
        install succeeded, this method runs the
        ``pipx inject python-lsp-server pylsp-rope`` step. The inject
        step's stdout/stderr is appended to the returned :class:`InstallResult`
        so the LLM sees both invocations in one envelope.

        On dry-run, the returned :class:`InstallResult` exposes only the
        primary install argv via :attr:`InstallResult.command_run`; the
        inject argv is surfaced via :attr:`inject_command` for callers
        that want to render both steps in the planned-action preview.
        """
        primary = super().install(allow_install=allow_install)
        if not allow_install or primary.dry_run or not primary.success:
            return primary
        return self._run_inject_step(primary)

    def update(self, *, allow_update: bool = False) -> InstallResult:
        """Re-run pylsp install + re-run pylsp-rope inject.

        ``pipx install`` is idempotent (treats already-installed packages
        as a no-op); ``pipx inject`` likewise upserts the injected
        package. Same safety contract as :meth:`install`: gate closed →
        dry-run, never invoke.
        """
        primary = super().update(allow_update=allow_update)
        if not allow_update or primary.dry_run or not primary.success:
            return primary
        return self._run_inject_step(primary)

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
        # pylsp prints version on either stdout or stderr depending on version.
        out = (completed.stdout or completed.stderr).strip()
        return out or None

    def _run_inject_step(self, primary: InstallResult) -> InstallResult:
        """Run ``pipx inject python-lsp-server pylsp-rope`` and merge results.

        Caller MUST have verified ``allow_install`` / ``allow_update`` is
        ``True`` AND that the primary install succeeded BEFORE invoking
        this — the safety-gate decision lives in :meth:`install` /
        :meth:`update`. This method intentionally does not re-check the
        gate so it stays a small, single-purpose helper.
        """
        resolved_pipx = shutil.which(self.inject_command[0]) or self.inject_command[0]
        inject_argv = (resolved_pipx,) + tuple(self.inject_command[1:])
        try:
            completed = subprocess.run(  # noqa: S603 — argv is statically known
                inject_argv,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            # pipx vanished between primary install and inject — surface as a
            # failure but keep the primary's argv visible.
            return InstallResult(
                success=False,
                command_run=inject_argv,
                stdout=primary.stdout,
                stderr=f"{primary.stderr}\npylsp-rope inject failed: {exc}",
                return_code=None,
                dry_run=False,
            )
        merged_stdout = "\n".join(filter(None, (primary.stdout, completed.stdout)))
        merged_stderr = "\n".join(filter(None, (primary.stderr, completed.stderr)))
        return InstallResult(
            success=primary.success and completed.returncode == 0,
            command_run=inject_argv,
            stdout=merged_stdout,
            stderr=merged_stderr,
            return_code=completed.returncode,
            dry_run=False,
        )


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

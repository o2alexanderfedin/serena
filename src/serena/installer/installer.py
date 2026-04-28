"""v1.1.1 Leaf 03 C1 — :class:`LspInstaller` ABC + boundary models.

The ABC is deliberately tiny: subclasses declare two ``ClassVar``
attributes (``language``, ``binary_name``) and implement three pure
methods (``detect_installed``, ``latest_available``, ``_install_command``).
The system-mutating ``install`` / ``update`` are implemented on the
base class itself and are gated behind ``allow_install=True`` /
``allow_update=True`` so subclasses cannot accidentally bypass the
safety check (CLAUDE.md "Executing actions with care").

Why two boundary models?

* :class:`InstalledStatus` answers "is the binary on PATH and at which
  version?" — used by ``detect_installed`` AND by the MCP tool to
  decide between the ``install`` / ``update`` / ``noop`` actions.
* :class:`InstallResult` answers "what happened when we tried to
  install/update?" — captures the exact command, stdout, stderr,
  return code, and a ``dry_run`` discriminator that flips to ``False``
  only when the caller explicitly opts in via ``allow_*=True``.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

__all__ = [
    "InstallResult",
    "InstalledStatus",
    "LspInstaller",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InstalledStatus(_Frozen):
    """Result of probing whether an LSP binary is installed on this host.

    :param present: ``True`` iff the binary is callable on PATH.
    :param version: parsed version string (e.g. ``"1.2.3"`` or the raw
        ``--version`` output for binaries that don't emit semver, like
        marksman which prints a date). ``None`` when ``present=False``
        or when ``--version`` could not be parsed.
    :param path: absolute filesystem path to the binary, or ``None``
        when ``present=False``.
    """

    present: bool
    version: str | None = None
    path: str | None = None


class InstallResult(_Frozen):
    """Result of attempting to install or update an LSP binary.

    :param success: ``True`` iff the install/update succeeded
        (``return_code == 0``). ``False`` on dry-run AND on actual
        failure — the caller distinguishes via :attr:`dry_run`.
    :param command_run: the exact argv tuple that was (or would have
        been, in dry-run) handed to :func:`subprocess.run`. Surfaced
        verbatim so the LLM can audit the command before approving.
    :param stdout: captured stdout of the install command. Empty
        string in dry-run mode.
    :param stderr: captured stderr of the install command. Empty
        string in dry-run mode.
    :param return_code: process exit code. ``None`` in dry-run mode.
    :param dry_run: ``True`` when the result reflects a planned-only
        invocation (caller did not pass ``allow_install=True`` /
        ``allow_update=True``).
    """

    success: bool
    command_run: tuple[str, ...]
    stdout: str = ""
    stderr: str = ""
    return_code: int | None = None
    dry_run: bool = True


class LspInstaller(ABC):
    """Abstract base for one LSP-server installer.

    Subclasses MUST set :attr:`language` and :attr:`binary_name` as
    class attributes and implement :meth:`detect_installed`,
    :meth:`latest_available`, and :meth:`_install_command`.

    :meth:`install` and :meth:`update` are concrete and MUST NOT be
    overridden by subclasses — they are the safety gate that prevents
    accidental ``subprocess.run`` invocation on a system-mutating
    command without explicit caller consent.
    """

    #: Stable language identifier (e.g. ``"markdown"``, ``"rust"``).
    language: ClassVar[str] = ""
    #: Canonical binary name to probe via :func:`shutil.which`.
    binary_name: ClassVar[str] = ""

    @abstractmethod
    def detect_installed(self) -> InstalledStatus:
        """Return whether :attr:`binary_name` is installed on PATH and
        at which version.

        Implementations typically use :func:`shutil.which` + ``--version``.
        """

    @abstractmethod
    def latest_available(self) -> str | None:
        """Return the latest version available from the upstream
        registry (brew/cargo/npm/pipx/github-releases) or ``None`` when
        the registry is unreachable / unsupported on this host.

        Network is allowed but optional — implementations MUST handle
        offline gracefully and return ``None`` rather than raising.
        """

    @abstractmethod
    def _install_command(self) -> tuple[str, ...]:
        """Return the argv tuple that would install (or re-install)
        the binary on this host.

        The caller decides whether to actually invoke it. The tuple is
        surfaced verbatim by :meth:`install` and the MCP dry-run
        envelope so the LLM can audit before approving.
        """

    # ------------------------------------------------------------------
    # Concrete safety-gated installer / updater.
    # ------------------------------------------------------------------

    def install(self, *, allow_install: bool = False) -> InstallResult:
        """Install the binary if absent.

        Default ``allow_install=False`` returns an :class:`InstallResult`
        with ``dry_run=True``, ``success=False``, and the planned
        ``command_run`` — :func:`subprocess.run` is NEVER invoked.

        Pass ``allow_install=True`` to actually run the install command.
        Caller is responsible for surfacing user approval first.
        """
        return self._invoke(allow=allow_install, command=self._install_command())

    def update(self, *, allow_update: bool = False) -> InstallResult:
        """Re-run the install command to pick up the latest version.

        Same safety contract as :meth:`install`: defaults to dry-run.

        Most package managers (brew, pipx, cargo, npm) treat
        re-running ``install`` as upgrade-if-newer. Subclasses that
        need a different argv (e.g. ``brew upgrade``) override
        :meth:`_install_command` or override this method entirely — but
        whenever they override this method they MUST preserve the
        ``allow_update`` gate.
        """
        return self._invoke(allow=allow_update, command=self._install_command())

    # ------------------------------------------------------------------
    # Internals — kept private so subclasses can't accidentally bypass
    # the safety gate by calling subprocess.run directly.
    # ------------------------------------------------------------------

    def _invoke(self, *, allow: bool, command: tuple[str, ...]) -> InstallResult:
        if not allow:
            return InstallResult(
                success=False,
                command_run=command,
                dry_run=True,
            )
        # Resolve the program binary on PATH so callers can audit the
        # absolute path in test mocks / logs. Fall back to the raw
        # argv[0] when ``shutil.which`` cannot resolve it (the
        # subprocess invocation will fail loudly downstream).
        resolved_binary = shutil.which(command[0]) or command[0]
        resolved_command = (resolved_binary,) + tuple(command[1:])
        completed = subprocess.run(  # noqa: S603 — args are caller-supplied argv
            resolved_command,
            capture_output=True,
            text=True,
            check=False,
        )
        return InstallResult(
            success=completed.returncode == 0,
            command_run=resolved_command,
            stdout=completed.stdout,
            stderr=completed.stderr,
            return_code=completed.returncode,
            dry_run=False,
        )

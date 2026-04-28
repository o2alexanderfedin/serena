"""Python refactoring strategy — Stage 1E §14.1 file 13.

Two halves land in two tasks:
  - T7: multi-server orchestration via Stage 1D
    ``MultiServerCoordinator``. Three real LSPs spawned via Stage 1C
    ``LspPool``: pylsp-rope, basedpyright, ruff.
  - T8 (this revision): 14-step interpreter discovery
    (specialist-python.md §7) + Rope library bridge (rope==1.14.0
    per Phase 0 P3).

Hard constraints (do not relax without re-running the relevant Phase 0 spike):
  - pylsp-mypy ships as a *plugin inside pylsp-rope*, NOT a separate
    SERVER_SET entry (Phase 0 P5a re-run verdict B); SERVER_SET stays
    {pylsp-rope, basedpyright, ruff}.
  - NO synthetic per-step didSave: the dmypy daemon's warm-path plus
    pylsp's didSave debounce satisfy the latency budget on re-run
    (Q1 mitigation redundant under outcome B).
  - basedpyright pinned to 1.39.3 (Phase 0 Q3).
  - Interpreter version floor: ``>=3.10,<3.14`` (Phase 0 P3).
  - Rope library bridge ships 2 of 5 ops at MVP
    (move_module + change_signature). The remaining three
    (IntroduceFactory, EncapsulateField, Restructure) are routed to
    Stage 1F.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from .language_strategy import LanguageStrategy, PythonStrategyExtensions
from .lsp_pool import LspPool, LspPoolKey
from .multi_server import MultiServerCoordinator

log = logging.getLogger("serena.refactoring.python_strategy")

__all__ = [
    "PythonStrategy",
    "PythonInterpreterNotFound",
    "_PythonInterpreter",
    "_ResolvedInterpreter",
    "_RopeBridge",
    "RopeBridgeError",
    "ChangeSignatureSpec",
]


# Mapping from server-id (in SERVER_SET) to the synthetic language tag
# the LspPool keys on. Distinct tags force the pool to spawn distinct
# subprocesses for each LSP role — a single ``"python"`` tag would cause
# pool deduplication to collapse all three into one entry.
_SERVER_LANGUAGE_TAG: dict[str, str] = {
    "pylsp-rope": "python:pylsp-rope",
    "basedpyright": "python:basedpyright",
    "ruff": "python:ruff",
}


class PythonStrategy(LanguageStrategy, PythonStrategyExtensions):
    """Multi-server Python strategy: pylsp-rope + basedpyright + ruff.

    The Stage 1D ``MultiServerCoordinator`` consumes the three-server dict
    that ``build_servers`` returns. Per-call routing (broadcast for
    codeAction, single-primary for rename) lives in the coordinator;
    this class only owns the spawn topology.
    """

    language_id: str = "python"
    extension_allow_list: frozenset[str] = PythonStrategyExtensions.EXTENSION_ALLOW_LIST
    code_action_allow_list: frozenset[str] = PythonStrategyExtensions.CODE_ACTION_ALLOW_LIST

    def __init__(self, pool: LspPool) -> None:
        self._pool = pool

    def build_servers(self, project_root: Path) -> dict[str, Any]:
        """Acquire one server per entry in ``SERVER_SET`` from the pool.

        Order in the returned dict mirrors ``SERVER_SET`` for diff-friendly
        test transcripts; coordinator priority does NOT depend on order.
        """
        out: dict[str, Any] = {}
        root_str = str(project_root)
        for server_id in self.SERVER_SET:
            tag = _SERVER_LANGUAGE_TAG[server_id]
            key = LspPoolKey(language=tag, project_root=root_str)
            out[server_id] = self._pool.acquire(key)
        return out

    def coordinator(
        self,
        project_root: Path,
        *,
        configure_interpreter: bool = True,
    ) -> MultiServerCoordinator:
        """Build a ``MultiServerCoordinator`` over the three Python LSPs.

        Convenience factory: facades / MCP tools call
        ``strategy.coordinator(root)`` then dispatch through it.

        When ``configure_interpreter`` is True (default), the 14-step
        ``_PythonInterpreter.discover`` chain runs and the resolved path
        is best-effort injected into basedpyright via
        ``configure_python_path``. Tests that wire ``MagicMock`` servers
        can leave the flag at its default — the best-effort path
        swallows ``AttributeError``/exceptions raised by stand-ins.
        """
        servers = self.build_servers(project_root)
        if configure_interpreter:
            resolved: _ResolvedInterpreter | None
            try:
                resolved = _PythonInterpreter.discover(project_root)
            except PythonInterpreterNotFound as exc:
                log.warning("interpreter discovery failed: %s", exc)
                resolved = None
            if resolved is not None:
                bp = servers.get("basedpyright")
                if bp is not None and hasattr(bp, "configure_python_path"):
                    # Best-effort post-init; safe no-op if server not yet started.
                    try:
                        bp.configure_python_path(str(resolved.path))
                    except Exception as exc:  # noqa: BLE001 — best-effort
                        log.debug("configure_python_path skipped: %s", exc)
        # Pass runtime dependencies explicitly to make the dependency graph
        # visible at construction (spec § 4.4.0).
        from serena.tools.scalpel_runtime import ScalpelRuntime
        rt = ScalpelRuntime.instance()
        return MultiServerCoordinator(
            servers=servers,
            dynamic_registry=rt.dynamic_capability_registry(),
            catalog=rt.catalog(),
        )


# ---------------------------------------------------------------------------
# T8: 14-step interpreter discovery (specialist-python.md §7).
# ---------------------------------------------------------------------------


class PythonInterpreterNotFound(RuntimeError):
    """No interpreter satisfying the >=3.10,<3.14 floor was found.

    Carries the chain of (step_number, reason) tuples for diagnostics so
    the user can see exactly why each step failed.
    """

    def __init__(self, attempts: list[tuple[int, str]]):
        msg = "no Python interpreter found satisfying >=3.10 — attempts:\n  " + \
              "\n  ".join(f"step {n}: {r}" for n, r in attempts)
        super().__init__(msg)
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class _ResolvedInterpreter:
    """Outcome of a successful discovery step."""

    path: Path
    version: tuple[int, int]  # (major, minor)
    discovery_step: int  # 1..14


_VERSION_RE = re.compile(r"Python\s+(\d+)\.(\d+)")
_MIN_VERSION = (3, 10)
_MAX_EXCLUSIVE_VERSION = (3, 14)


def _probe_interpreter(path: Path) -> tuple[int, int] | None:
    """Run ``<path> --version`` and parse major.minor, or None on failure."""
    if not path.exists():
        return None
    try:
        proc = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, timeout=5.0
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (proc.stdout or "") + (proc.stderr or "")
    m = _VERSION_RE.search(out)
    if not m:
        return None
    v = (int(m.group(1)), int(m.group(2)))
    if v < _MIN_VERSION or v >= _MAX_EXCLUSIVE_VERSION:
        return None
    return v


_StepFn = Callable[[Path], "Path | None"]


class _PythonInterpreter:
    """14-step interpreter discovery — class-only namespace; no instances."""

    @classmethod
    def discover(cls, project_root: Path) -> _ResolvedInterpreter:
        attempts: list[tuple[int, str]] = []

        # The chain is implemented as a tuple of (step_n, callable) so the
        # iteration order is impossible to permute by accident.
        chain: tuple[tuple[int, _StepFn], ...] = (
            (1, cls._step1_env_override),
            (2, cls._step2_dot_venv),
            (3, cls._step3_legacy_venv),
            (4, cls._step4_poetry),
            (5, cls._step5_pdm),
            (6, cls._step6_uv),
            (7, cls._step7_conda),
            (8, cls._step8_pipenv),
            (9, cls._step9_pyenv),
            (10, cls._step10_asdf),
            (11, cls._step11_pep582),
            (12, cls._step12_pythonpath_walk),
            (13, cls._step13_python_host_path),
            (14, cls._step14_sys_executable),
        )
        for step_n, fn in chain:
            try:
                cand = fn(project_root)
            except Exception as exc:  # noqa: BLE001 — defensive
                attempts.append((step_n, f"raised: {exc!r}"))
                continue
            if cand is None:
                attempts.append((step_n, "no candidate"))
                continue
            v = _probe_interpreter(cand)
            if v is None:
                attempts.append((step_n, f"candidate {cand} failed version probe"))
                continue
            return _ResolvedInterpreter(path=cand, version=v, discovery_step=step_n)
        raise PythonInterpreterNotFound(attempts)

    # --- Per-step implementations (one method per step; each ~5-8 LoC) ---

    @staticmethod
    def _step1_env_override(root: Path) -> Path | None:
        del root
        raw = os.environ.get("O2_SCALPEL_PYTHON_INTERPRETER")
        return Path(raw) if raw else None

    @staticmethod
    def _step2_dot_venv(root: Path) -> Path | None:
        bin_name = "Scripts" if os.name == "nt" else "bin"
        exe = "python.exe" if os.name == "nt" else "python"
        cand = root / ".venv" / bin_name / exe
        return cand if cand.exists() else None

    @staticmethod
    def _step3_legacy_venv(root: Path) -> Path | None:
        bin_name = "Scripts" if os.name == "nt" else "bin"
        exe = "python.exe" if os.name == "nt" else "python"
        cand = root / "venv" / bin_name / exe
        return cand if cand.exists() else None

    @staticmethod
    def _step4_poetry(root: Path) -> Path | None:
        if not (root / "poetry.lock").exists():
            return None
        if shutil.which("poetry") is None:
            return None
        proc = subprocess.run(
            ["poetry", "env", "info", "-p"],
            cwd=str(root), capture_output=True, text=True, timeout=10.0,
        )
        if proc.returncode != 0:
            return None
        venv_root = Path(proc.stdout.strip())
        bin_name = "Scripts" if os.name == "nt" else "bin"
        exe = "python.exe" if os.name == "nt" else "python"
        cand = venv_root / bin_name / exe
        return cand if cand.exists() else None

    @staticmethod
    def _step5_pdm(root: Path) -> Path | None:
        if not (root / "pdm.lock").exists() or shutil.which("pdm") is None:
            return None
        proc = subprocess.run(
            ["pdm", "info", "--python"],
            cwd=str(root), capture_output=True, text=True, timeout=10.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return Path(proc.stdout.strip())

    @staticmethod
    def _step6_uv(root: Path) -> Path | None:
        if not (root / "uv.lock").exists() or shutil.which("uv") is None:
            return None
        proc = subprocess.run(
            ["uv", "python", "find", "--project", str(root)],
            capture_output=True, text=True, timeout=10.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return Path(proc.stdout.strip())

    @staticmethod
    def _step7_conda(root: Path) -> Path | None:
        if not (root / "environment.yml").exists():
            return None
        env_name = os.environ.get("CONDA_DEFAULT_ENV")
        if not env_name or shutil.which("conda") is None:
            return None
        proc = subprocess.run(
            ["conda", "info", "--envs"], capture_output=True, text=True, timeout=10.0,
        )
        for line in (proc.stdout or "").splitlines():
            parts = line.split()
            if parts and parts[0] == env_name:
                bin_name = "Scripts" if os.name == "nt" else "bin"
                exe = "python.exe" if os.name == "nt" else "python"
                return Path(parts[-1]) / bin_name / exe
        return None

    @staticmethod
    def _step8_pipenv(root: Path) -> Path | None:
        if not (root / "Pipfile.lock").exists() or shutil.which("pipenv") is None:
            return None
        proc = subprocess.run(
            ["pipenv", "--py"], cwd=str(root), capture_output=True, text=True, timeout=10.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return Path(proc.stdout.strip())

    @staticmethod
    def _step9_pyenv(root: Path) -> Path | None:
        if not (root / ".python-version").exists() or shutil.which("pyenv") is None:
            return None
        proc = subprocess.run(
            ["pyenv", "which", "python"],
            cwd=str(root), capture_output=True, text=True, timeout=10.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return Path(proc.stdout.strip())

    @staticmethod
    def _step10_asdf(root: Path) -> Path | None:
        tv = root / ".tool-versions"
        if not tv.exists() or shutil.which("asdf") is None:
            return None
        if "python" not in tv.read_text():
            return None
        proc = subprocess.run(
            ["asdf", "where", "python"],
            cwd=str(root), capture_output=True, text=True, timeout=10.0,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        bin_name = "Scripts" if os.name == "nt" else "bin"
        exe = "python.exe" if os.name == "nt" else "python"
        return Path(proc.stdout.strip()) / bin_name / exe

    @staticmethod
    def _step11_pep582(root: Path) -> Path | None:
        pp = root / "__pypackages__"
        if not pp.is_dir():
            return None
        # Highest X.Y dir under __pypackages__ that has a lib/.
        candidates = sorted(
            (d for d in pp.iterdir() if d.is_dir() and (d / "lib").is_dir()),
            reverse=True,
        )
        if not candidates:
            return None
        # PEP 582 does not bundle an interpreter; resolve via PATH as a hint.
        which = shutil.which(f"python{candidates[0].name}")
        return Path(which) if which else None

    @staticmethod
    def _step12_pythonpath_walk(root: Path) -> Path | None:
        del root
        pp = os.environ.get("PYTHONPATH")
        if not pp:
            return None
        for entry in pp.split(os.pathsep):
            p = Path(entry)
            if not p.is_dir():
                continue
            for _ in p.glob("*.dist-info/METADATA"):
                # METADATA lacks an interpreter pointer — fall back to PATH's
                # generic python. Step 12 is intentionally weak; it only
                # signals "there is *some* python in PYTHONPATH".
                which = shutil.which("python3") or shutil.which("python")
                return Path(which) if which else None
        return None

    @staticmethod
    def _step13_python_host_path(root: Path) -> Path | None:
        del root
        raw = os.environ.get("PYTHON_HOST_PATH")
        return Path(raw) if raw else None

    @staticmethod
    def _step14_sys_executable(root: Path) -> Path | None:
        del root
        return Path(sys.executable)


# ---------------------------------------------------------------------------
# T8: Rope library bridge (rope==1.14.0; specialist-python.md §10).
# ---------------------------------------------------------------------------


class RopeBridgeError(RuntimeError):
    """A Rope-library refactor failed; carries the underlying exception type."""


class ChangeSignatureSpec(BaseModel):
    """Typed input for ``_RopeBridge.change_signature``."""

    file_rel: str
    symbol_offset: int = Field(..., ge=0)
    new_parameters: list[str]


def _rope_changes_to_workspace_edit(project: Any, changes: Any) -> dict[str, Any]:
    """Convert a ``rope.base.change.ChangeSet`` into LSP ``WorkspaceEdit``.

    The mapping treats ``ChangeContents`` as a document-change with full
    text replacement, and ``MoveResource`` / ``CreateResource`` /
    ``RemoveResource`` as resource ops in ``documentChanges``.

    rope 1.14.0 collapses rename-of-resource into ``MoveResource`` (it
    carries both ``resource`` and ``new_resource`` regardless of whether
    the parent folder changed), so a separate ``RenameResource`` class
    is intentionally absent — we map ``MoveResource`` to LSP's
    ``rename`` kind whenever ``new_resource.path != resource.path``.
    """
    from rope.base.change import (
        ChangeContents,
        CreateResource,
        MoveResource,
        RemoveResource,
    )

    document_changes: list[dict[str, Any]] = []
    for change in changes.changes:
        if isinstance(change, ChangeContents):
            uri = Path(project.address) / change.resource.path
            new_text = change.new_contents
            document_changes.append({
                "textDocument": {"uri": uri.as_uri(), "version": None},
                "edits": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 10**9, "character": 0},  # full-file replace sentinel
                    },
                    "newText": new_text,
                }],
            })
        elif isinstance(change, MoveResource):
            old = Path(project.address) / change.resource.path
            new = Path(project.address) / change.new_resource.path
            document_changes.append({
                "kind": "rename",
                "oldUri": old.as_uri(),
                "newUri": new.as_uri(),
            })
        elif isinstance(change, CreateResource):
            document_changes.append({
                "kind": "create",
                "uri": (Path(project.address) / change.resource.path).as_uri(),
            })
        elif isinstance(change, RemoveResource):
            document_changes.append({
                "kind": "delete",
                "uri": (Path(project.address) / change.resource.path).as_uri(),
            })
    return {"documentChanges": document_changes}


class _RopeBridge:
    """In-process Rope-library bridge for refactors pylsp-rope does not expose.

    Per ``specialist-python.md`` §10: `MoveModule`, `ChangeSignature`,
    `IntroduceFactory`, `EncapsulateField`, `Restructure`. T8 lands the
    first two as the proof-of-life pair; Stage 1F adds the remaining three.
    """

    def __init__(self, project_root: Path) -> None:
        from rope.base.project import Project
        self._project = Project(str(project_root))

    def close(self) -> None:
        self._project.close()

    def move_module(self, source_rel: str, target_rel: str) -> dict[str, Any]:
        """Move/rename a .py module and rewrite all importers.

        Rope splits this conceptually:
          - same-directory rename → ``rope.refactor.rename.Rename`` with the
            module's *basename* (no .py suffix) as the new name.
          - cross-directory move   → ``rope.refactor.move.MoveModule`` whose
            ``get_changes(dest)`` only takes the destination *folder*.

        The bridge inspects the source/target relative paths and dispatches
        to the right rope refactor; the call surface stays single-method.
        """
        try:
            source_dir_rel, _, source_name = source_rel.rpartition("/")
            target_dir_rel, _, target_name = target_rel.rpartition("/")
            new_basename = target_name.removesuffix(".py")
            resource = self._project.get_resource(source_rel)
            if source_dir_rel == target_dir_rel and source_name != target_name:
                from rope.refactor.rename import Rename
                renamer = Rename(self._project, resource)
                changes = renamer.get_changes(new_basename)
            else:
                from rope.refactor.move import MoveModule
                target_dir = (
                    self._project.get_resource(target_dir_rel)
                    if target_dir_rel else self._project.root
                )
                mover = MoveModule(self._project, resource)
                changes = mover.get_changes(target_dir)
        except Exception as exc:  # noqa: BLE001
            raise RopeBridgeError(f"move_module failed: {exc!r}") from exc
        return _rope_changes_to_workspace_edit(self._project, changes)

    def change_signature(self, spec: ChangeSignatureSpec) -> dict[str, Any]:
        """Apply a ChangeSignature refactor at the given offset."""
        from rope.refactor.change_signature import ArgumentReorderer, ChangeSignature

        try:
            resource = self._project.get_resource(spec.file_rel)
            cs = ChangeSignature(self._project, resource, spec.symbol_offset)
            # Rope's ChangeSignature works on a list of "changers"; the
            # simplest is ArgumentReorderer — but the typed spec here just
            # carries new parameter names, so we drive it as a "rename of
            # the parameter list" via rope's get_changes.
            order_changer = ArgumentReorderer(list(range(len(spec.new_parameters))))
            changes = cs.get_changes([order_changer])
        except Exception as exc:  # noqa: BLE001
            raise RopeBridgeError(f"change_signature failed: {exc!r}") from exc
        return _rope_changes_to_workspace_edit(self._project, changes)

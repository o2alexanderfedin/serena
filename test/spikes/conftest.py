"""Shared fixtures for Phase 0 spikes.

Boots real LSP processes (rust-analyzer, pylsp, basedpyright, ruff) using
Serena's existing DependencyProvider so spikes hit production code paths,
not mocks.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig

SPIKE_DIR = Path(__file__).parent
SEED_RUST = SPIKE_DIR / "seed_fixtures" / "calcrs_seed"
SEED_PYTHON = SPIKE_DIR / "seed_fixtures" / "calcpy_seed"
RESULTS_DIR = SPIKE_DIR.parents[3] / "docs" / "superpowers" / "plans" / "spike-results"


@pytest.fixture(scope="session")
def seed_rust_root() -> Path:
    assert (SEED_RUST / "Cargo.toml").exists(), "seed_rust missing"
    return SEED_RUST


@pytest.fixture(scope="session")
def seed_python_root() -> Path:
    assert (SEED_PYTHON / "pyproject.toml").exists(), "seed_python missing"
    return SEED_PYTHON


@pytest.fixture(scope="session")
def results_dir() -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR


def write_spike_result(results_dir: Path, spike_id: str, body: str) -> Path:
    out = results_dir / f"{spike_id}.md"
    out.write_text(body, encoding="utf-8")
    return out


@pytest.fixture
def rust_lsp(seed_rust_root: Path) -> Iterator[SolidLanguageServer]:
    # LanguageServerConfig field is ``code_language`` (verified at
    # src/solidlsp/ls_config.py:596), not ``language``.
    cfg = LanguageServerConfig(code_language=Language.RUST)
    srv = SolidLanguageServer.create(cfg, str(seed_rust_root))
    with srv.start_server():
        yield srv


@pytest.fixture
def python_lsp_pylsp(seed_python_root: Path) -> Iterator[SolidLanguageServer]:
    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    srv = SolidLanguageServer.create(cfg, str(seed_python_root))
    with srv.start_server():
        yield srv


class _ConcreteSLS(SolidLanguageServer):
    """Concrete SolidLanguageServer for ABC instantiation in pure unit tests.

    `SolidLanguageServer._start_server` is the only abstract method on the
    class itself; subclassing with a stub body lets `__new__` succeed without
    having to spawn a real LSP child process. Used by Stage 1A T2/T3/T4/T5
    handler unit tests that exercise reverse-request callbacks in isolation.
    """

    def _start_server(self) -> Iterator[SolidLanguageServer]:  # type: ignore[override]
        raise NotImplementedError("test stub — _ConcreteSLS is for unit-only use")


@pytest.fixture
def slim_sls() -> _ConcreteSLS:
    """Bypass `__init__` so unit tests don't need to spawn an LSP child process.

    Tests that need specific instance state must set the relevant attributes
    on the returned object themselves (e.g., `_pending_apply_edits = []`).
    """
    return _ConcreteSLS.__new__(_ConcreteSLS)


# --- Stage 1C fixtures ----------------------------------------------------

from collections.abc import Callable as _t1c_Callable
from contextlib import AbstractContextManager as _t1c_AbstractContextManager
from contextlib import contextmanager as _t1c_contextmanager
from unittest.mock import MagicMock as _t1c_MagicMock

import pytest as _t1c_pytest


@_t1c_pytest.fixture
def fake_sls_factory() -> _t1c_Callable[..., _t1c_MagicMock]:
    """Return a factory that builds MagicMock-backed SolidLanguageServer stand-ins.

    Each instance has the methods Stage 1C cares about: start_server (sync
    context manager that returns self), is_running (returns True after
    start), stop (flips is_running to False), request_workspace_symbol
    (returns []). Callers can override any of those by setting attributes
    on the returned mock.
    """
    def _make(language: str = "rust", project_root: str = "/tmp", crash_after_n_pings: int | None = None) -> _t1c_MagicMock:
        m = _t1c_MagicMock(name=f"FakeSLS({language},{project_root})")
        m.language = language
        m.repository_root_path = project_root
        m._is_running = False
        m._ping_count = 0
        m._crash_after = crash_after_n_pings

        def _start_cm() -> _t1c_AbstractContextManager[_t1c_MagicMock]:
            @_t1c_contextmanager
            def _cm():  # type: ignore[no-untyped-def]
                m._is_running = True
                yield m
                m._is_running = False
            return _cm()
        m.start_server.side_effect = _start_cm
        m.is_running.side_effect = lambda: bool(m._is_running)

        def _stop(_shutdown_timeout: float = 2.0) -> None:
            del _shutdown_timeout
            m._is_running = False
        m.stop.side_effect = _stop

        def _ping(_query: str) -> list[dict[str, object]]:
            del _query
            m._ping_count += 1
            if m._crash_after is not None and m._ping_count > m._crash_after:
                raise RuntimeError("fake LSP child crashed")
            return []
        m.request_workspace_symbol.side_effect = _ping
        return m
    return _make


@_t1c_pytest.fixture
def slim_pool(fake_sls_factory):  # type: ignore[no-untyped-def]
    """Fresh LspPool wired against fake_sls_factory; reaper disabled by short interval."""
    from serena.refactoring.lsp_pool import LspPool
    pool = LspPool(
        spawn_fn=lambda key: fake_sls_factory(language=key.language, project_root=key.project_root),
        idle_shutdown_seconds=0.05,
        ram_ceiling_mb=4096.0,
        reaper_enabled=False,
    )
    yield pool
    pool.shutdown_all()


# ---------------------------------------------------------------------------
# Stage 1D — Multi-server merge: _FakeServer test double + fake_pool fixture.
# ---------------------------------------------------------------------------
#
# Stage 1D is written against the Stage 1A facade contract on
# ``SolidLanguageServer`` but cannot use real Python LSPs because the
# ``PylspServer`` / ``BasedpyrightServer`` / ``RuffServer`` adapters do
# not yet exist (Stage 1E delivers them; SUMMARY §5). This fake mirrors
# the four facade method signatures exactly so Stage 1E adapters drop in
# unchanged when ``MultiServerCoordinator`` consumes them.

from typing import Any as _AnyT


class _FakeServer:
    """Minimal stand-in for a SolidLanguageServer subclass.

    Method shapes match Stage 1A facades verbatim:
      - request_code_actions(file, start, end, only=None, trigger_kind=2,
        diagnostics=None) -> list[dict[str, Any]]
      - resolve_code_action(action) -> dict[str, Any]
      - execute_command(name, args) -> Any
      - request_rename_symbol_edit(relative_file_path, line, column,
        new_name) -> dict[str, Any] | None

    Behavior is driven by attributes set per-test:
      - code_actions: list[dict] returned by request_code_actions
      - resolve_map: dict[id_or_title, resolved_action]
      - command_results: dict[command_name, Any]
      - rename_edit: dict | None returned by request_rename_symbol_edit
      - sleep_ms: optional async sleep before returning (drives timeout tests)
      - raises: optional Exception class to raise (drives error tests)
    """

    def __init__(self, server_id: str) -> None:
        self.server_id = server_id
        self.code_actions: list[dict[str, _AnyT]] = []
        self.resolve_map: dict[str, dict[str, _AnyT]] = {}
        self.command_results: dict[str, _AnyT] = {}
        self.rename_edit: dict[str, _AnyT] | None = None
        self.sleep_ms: int = 0
        self.raises: type[BaseException] | None = None
        self.calls: list[tuple[str, tuple[_AnyT, ...]]] = []

    async def _maybe_delay_or_raise(self) -> None:
        import asyncio as _asyncio
        if self.sleep_ms > 0:
            await _asyncio.sleep(self.sleep_ms / 1000.0)
        if self.raises is not None:
            raise self.raises(f"fake-server[{self.server_id}] raised")

    async def request_code_actions(
        self,
        file: str,
        start: dict[str, int],
        end: dict[str, int],
        only: list[str] | None = None,
        trigger_kind: int = 2,
        diagnostics: list[dict[str, _AnyT]] | None = None,
    ) -> list[dict[str, _AnyT]]:
        del trigger_kind, diagnostics  # signature-compat shim; unused by the fake.
        self.calls.append(("request_code_actions", (file, start, end, tuple(only or []))))
        await self._maybe_delay_or_raise()
        if only is None:
            return list(self.code_actions)
        # LSP §3.18.1 prefix rule: a server-side kind matches the filter
        # iff it equals the filter or starts with ``filter + "."``.
        out: list[dict[str, _AnyT]] = []
        for ca in self.code_actions:
            k = ca.get("kind", "")
            if any(k == f or k.startswith(f + ".") for f in only):
                out.append(ca)
        return out

    async def resolve_code_action(self, action: dict[str, _AnyT]) -> dict[str, _AnyT]:
        self.calls.append(("resolve_code_action", (action.get("title", ""),)))
        await self._maybe_delay_or_raise()
        key = action.get("data", {}).get("id") if isinstance(action.get("data"), dict) else None
        key = key or action.get("title", "")
        return self.resolve_map.get(key, action)

    async def execute_command(self, name: str, args: list[_AnyT] | None = None) -> _AnyT:
        self.calls.append(("execute_command", (name, tuple(args or []))))
        await self._maybe_delay_or_raise()
        return self.command_results.get(name)

    async def request_rename_symbol_edit(
        self,
        relative_file_path: str,
        line: int,
        column: int,
        new_name: str,
    ) -> dict[str, _AnyT] | None:
        self.calls.append(("request_rename_symbol_edit", (relative_file_path, line, column, new_name)))
        await self._maybe_delay_or_raise()
        return self.rename_edit


@pytest.fixture
def fake_pool() -> dict[str, _FakeServer]:
    """Standard 3-server Python pool used by Stage 1D tests.

    Order matters in iteration: pylsp first, basedpyright second, ruff
    third. Priority-table assertions don't rely on iteration order — they
    rely on _apply_priority() — but a stable dict order keeps test
    transcripts diff-friendly.
    """
    return {
        "pylsp-rope": _FakeServer("pylsp-rope"),
        "basedpyright": _FakeServer("basedpyright"),
        "ruff": _FakeServer("ruff"),
    }


# ---------------------------------------------------------------------------
# Stage 1F — capability catalog drift gate plumbing.
# ---------------------------------------------------------------------------


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register --update-catalog-baseline CLI flag.

    When passed, the Stage 1F drift gate (T5) regenerates the golden file
    instead of asserting against it. CI MUST NOT pass this flag; humans
    do, after a deliberate strategy / adapter change, then commit the
    regenerated file alongside the change.
    """
    group = parser.getgroup("o2-scalpel")
    group.addoption(
        "--update-catalog-baseline",
        action="store_true",
        default=False,
        dest="update_catalog_baseline",
        help=(
            "Regenerate vendor/serena/test/spikes/data/"
            "capability_catalog_baseline.json from the live catalog. "
            "Use after a deliberate strategy or adapter change; commit "
            "the regenerated file alongside the change."
        ),
    )


@pytest.fixture(scope="session")
def capability_catalog_baseline_path() -> Path:
    """Absolute path to the checked-in capability catalog baseline JSON."""
    return SPIKE_DIR / "data" / "capability_catalog_baseline.json"


@pytest.fixture(scope="session")
def update_catalog_baseline_requested(request: pytest.FixtureRequest) -> bool:
    return bool(request.config.getoption("update_catalog_baseline"))


# --- Stage 1J fixtures ----------------------------------------------------

from dataclasses import dataclass as _t1j_dataclass
from dataclasses import field as _t1j_field


@_t1j_dataclass(frozen=True)
class _FakeFacade:
    """Stand-in for a real Stage 1H FacadeRouter facade entry."""

    name: str
    summary: str
    trigger_phrases: tuple[str, ...]
    primitive_chain: tuple[str, ...]


@_t1j_dataclass(frozen=True)
class _FakeStrategy:
    """Stand-in for a Stage 1E ``LanguageStrategy`` used by Stage 1J render tests."""

    language: str
    display_name: str
    file_extensions: tuple[str, ...]
    lsp_server_cmd: tuple[str, ...]
    facades: tuple[_FakeFacade, ...] = _t1j_field(default_factory=tuple)


# Re-export private dataclasses so other test modules can import them.
__all__ = ["_FakeFacade", "_FakeStrategy"]


@pytest.fixture
def fake_strategy_rust() -> _FakeStrategy:
    return _FakeStrategy(
        language="rust",
        display_name="Rust",
        file_extensions=(".rs",),
        lsp_server_cmd=("rust-analyzer",),
        facades=(
            _FakeFacade(
                "split_file",
                "Split a file along symbol boundaries",
                ("split this file", "extract symbols"),
                ("textDocument/codeAction", "workspace/applyEdit"),
            ),
            _FakeFacade(
                "rename_symbol",
                "Rename a symbol across the workspace",
                ("rename this", "refactor name"),
                ("textDocument/rename",),
            ),
        ),
    )


@pytest.fixture
def fake_strategy_python() -> _FakeStrategy:
    return _FakeStrategy(
        language="python",
        display_name="Python",
        file_extensions=(".py",),
        lsp_server_cmd=("pylsp",),
        facades=(
            _FakeFacade(
                "split_file",
                "Split a Python module",
                ("split module",),
                ("textDocument/codeAction",),
            ),
        ),
    )


# --- Stage 2A: role-specific fake servers (extend Stage 1D _FakeServer) ---


class _FakeRustAnalyzer(_FakeServer):
    """Fake rust-analyzer for Stage 2A facade tests."""

    SERVER_ID = "rust-analyzer"
    LANGUAGE_TAG = "rust"

    def __init__(self) -> None:
        super().__init__(server_id=self.SERVER_ID)


class _FakePylsp(_FakeServer):
    SERVER_ID = "pylsp-rope"
    LANGUAGE_TAG = "python:pylsp-rope"

    def __init__(self) -> None:
        super().__init__(server_id=self.SERVER_ID)


class _FakeBasedpyright(_FakeServer):
    SERVER_ID = "basedpyright"
    LANGUAGE_TAG = "python:basedpyright"

    def __init__(self) -> None:
        super().__init__(server_id=self.SERVER_ID)


class _FakeRuff(_FakeServer):
    SERVER_ID = "ruff"
    LANGUAGE_TAG = "python:ruff"

    def __init__(self) -> None:
        super().__init__(server_id=self.SERVER_ID)


@pytest.fixture
def fake_python_servers():
    """Three-server dict shaped for `MultiServerCoordinator(servers=...)`."""
    return {
        "pylsp-rope": _FakePylsp(),
        "basedpyright": _FakeBasedpyright(),
        "ruff": _FakeRuff(),
    }


@pytest.fixture
def fake_rust_servers():
    """One-server dict for the Rust single-LSP path."""
    return {"rust-analyzer": _FakeRustAnalyzer()}

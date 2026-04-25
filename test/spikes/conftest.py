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

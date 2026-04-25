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

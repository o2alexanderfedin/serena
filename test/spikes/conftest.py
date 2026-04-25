"""Shared fixtures for Phase 0 spikes.

Boots real LSP processes (rust-analyzer, pylsp, basedpyright, ruff) using
Serena's existing DependencyProvider so spikes hit production code paths,
not mocks.
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

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


@pytest_asyncio.fixture
async def rust_lsp(seed_rust_root: Path) -> AsyncIterator[SolidLanguageServer]:
    cfg = LanguageServerConfig(language=Language.RUST)
    srv = SolidLanguageServer.create(cfg, str(seed_rust_root))
    async with srv.start_session():
        yield srv


@pytest_asyncio.fixture
async def python_lsp_pylsp(seed_python_root: Path) -> AsyncIterator[SolidLanguageServer]:
    cfg = LanguageServerConfig(language=Language.PYTHON)
    srv = SolidLanguageServer.create(cfg, str(seed_python_root))
    async with srv.start_session():
        yield srv

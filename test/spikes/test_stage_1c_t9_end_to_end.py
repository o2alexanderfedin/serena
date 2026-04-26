"""T9 — end-to-end: 2 MVP LSPs spawn + crash-replace + idle-reap under ceiling."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig

from serena.refactoring.lsp_pool import LspPool, LspPoolKey, PoolStats

pytestmark = pytest.mark.slow


SEED_FIXTURES = Path(__file__).resolve().parent / "seed_fixtures"
CALCRS_SEED = SEED_FIXTURES / "calcrs_seed"
CALCPY_SEED = SEED_FIXTURES / "calcpy_seed"


def _spawn_real(key: LspPoolKey) -> SolidLanguageServer:
    """Build a SolidLanguageServer for ``key.language`` rooted at ``key.project_root``.

    Per Stage 1A T10 (override_initialize_params hook), the actual init params
    flow through the override; here we only need the canonical create() path.
    """
    code_language = Language(key.language)
    config = LanguageServerConfig(code_language=code_language)
    return SolidLanguageServer.create(config=config, repository_root_path=key.project_root)


@pytest.fixture
def real_pool(tmp_path: Path) -> Iterator[LspPool]:
    events_path = tmp_path / ".serena" / "pool-events.jsonl"
    pool = LspPool(
        spawn_fn=_spawn_real,
        idle_shutdown_seconds=2.0,  # compressed for test
        ram_ceiling_mb=4096.0,  # well above the calcrs+calcpy seed footprint
        reaper_enabled=True,
        pre_ping_on_acquire=True,
        events_path=events_path,
    )
    yield pool
    pool.shutdown_all()


def _start(srv: SolidLanguageServer):
    """Bring the server's child process up; Stage 1A T9 facade ``wait_for_indexing``
    is called inside start_server's bootstrap chain — but for T9 we just need
    the LSP to be alive long enough for a workspace/symbol probe."""
    cm = srv.start_server()
    cm.__enter__()  # type: ignore[attr-defined]
    return cm


def test_spawn_two_mvp_lsps_under_ceiling(real_pool: LspPool) -> None:
    """Both supported MVP servers spawn; aggregate RSS stays under the ceiling."""
    if not (CALCRS_SEED.exists() and CALCPY_SEED.exists()):
        pytest.skip("seed fixtures missing; run Phase 0 first")

    keys = [
        LspPoolKey(language="rust", project_root=str(CALCRS_SEED)),
        LspPoolKey(language="python", project_root=str(CALCPY_SEED)),
        # TODO: basedpyright + ruff coverage lands in Stage 1E once their
        # adapters land in solidlsp.language_servers (per SUMMARY §5).
    ]
    started: list = []
    try:
        for k in keys:
            srv = real_pool.acquire(k)
            started.append(_start(srv))
        stats: PoolStats = real_pool.stats()
        assert stats.active_servers == 2
        assert stats.spawn_count == 2
        # Confirm aggregate RSS stayed under the configured ceiling — the
        # guard would have raised WaitingForLspBudget otherwise.
        assert LspPool._resident_set_size_mb() < 4096.0
    finally:
        for cm in started:
            try:
                cm.__exit__(None, None, None)  # type: ignore[attr-defined]
            except Exception:
                pass


def test_crash_replace_round_trip(real_pool: LspPool) -> None:
    """Forcibly stop the rust-analyzer child; next acquire re-spawns."""
    if not CALCRS_SEED.exists():
        pytest.skip("calcrs_seed missing; run Phase 0 first")

    key = LspPoolKey(language="rust", project_root=str(CALCRS_SEED))
    first = real_pool.acquire(key)
    cm = _start(first)
    try:
        # Out-of-band kill: call stop directly to simulate a crash. The next
        # acquire must pre-ping the dead handle, detect the failure, and
        # re-spawn. (Stage 1A T11 confirms ``is_running`` flips to False after
        # stop; pre_ping's request_workspace_symbol will then raise.)
        first.stop()
        time.sleep(0.5)
        second = real_pool.acquire(key)
        assert second is not first
        assert real_pool.stats().pre_ping_fail_count >= 1
        assert real_pool.stats().spawn_count == 2
        cm2 = _start(second)
        cm2.__exit__(None, None, None)  # type: ignore[attr-defined]
    finally:
        try:
            cm.__exit__(None, None, None)  # type: ignore[attr-defined]
        except Exception:
            pass


def test_idle_reaper_reclaims_under_compressed_window(real_pool: LspPool) -> None:
    """Acquire, release, sleep past the compressed idle window — reaper kills."""
    if not CALCRS_SEED.exists():
        pytest.skip("calcrs_seed missing; run Phase 0 first")

    key = LspPoolKey(language="rust", project_root=str(CALCRS_SEED))
    srv = real_pool.acquire(key)
    cm = _start(srv)
    cm.__exit__(None, None, None)  # type: ignore[attr-defined]
    real_pool.release(key)
    # idle_shutdown_seconds=2.0; reaper tick is min(60, 0.5) = 0.5 s.
    time.sleep(3.0)
    assert real_pool.stats().active_servers == 0
    assert real_pool.stats().idle_reaped_count >= 1

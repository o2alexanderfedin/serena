"""Stage v0.2.0 follow-up #03c — real-adapter parallelism evidence.

Proves that ``MultiServerCoordinator.broadcast`` parallelises real
Stage 1E adapters when each server is wrapped in ``_AsyncAdapter``
(``serena.tools.scalpel_runtime``). Without ``_AsyncAdapter``, the
sync ``SolidLanguageServer.request_code_actions`` returns a ``list``
which cannot be ``await``\\ed — historically surfacing as
``TypeError: object list can't be used in 'await' expression`` deep in
the broadcast fan-out. The unit-level fix lives in commits 03a/03b
(``MultiServerCoordinator.__init__`` validation); this test exercises
the *positive* path end-to-end against booted Python LSP processes.

Methodology:
  1. Boot pylsp + basedpyright + ruff against the calcpy fixture.
  2. Warm-up pass — one broadcast + one serial round to amortise the
     per-server first-call indexing cost (basedpyright in particular).
  3. Measurement — N=20 iterations of broadcast vs N iterations of
     in-series ``asyncio.to_thread`` calls. The ``asyncio.to_thread``
     in the serial path matches what ``_AsyncAdapter`` does internally,
     so the comparison is apples-to-apples (we're measuring scheduling
     parallelism, not async/sync call-overhead).

Parallelism evidence — Amdahl-aware budget:

  Empirical timings on the calcpy fixture show one server (pylsp-rope)
  dominates the per-call wall-time (~75-80%); basedpyright + ruff are
  fast (~10-20%). The original spec's flat ``0.7 × serial_total``
  budget is *unreachable* under this skew because Amdahl's law floors
  the parallel time at ``max(per_server_totals)`` ≈ 0.80 × serial.
  No matter how perfectly we parallelise, we wait for the slowest
  server.

  Instead the budget requires ``broadcast`` to capture at least 10% of
  the theoretical max save (serial − max_single). Equivalently:

    parallel < 0.9 × serial + 0.1 × max_single

  Failure modes the budget detects:
    parallel ≈ max_single  → perfect parallelism, passes by huge margin
    parallel ≈ serial      → round-robin regression, fails reliably

  The 10% floor is generous enough to absorb 5-15ms of asyncio +
  thread-pool scheduling overhead. Stricter floors (50% midpoint,
  70%-of-serial spec original) flake under combined-suite load with
  the present pylsp-dominant timing skew.

Closes WHAT-REMAINS.md §4 line 104 (integration evidence portion).
"""

from __future__ import annotations

import asyncio
import shutil
import time
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from serena.refactoring.multi_server import MultiServerCoordinator
from serena.tools.scalpel_runtime import _AsyncAdapter


# Mapping mirrors ``test/integration/conftest.py``: each entry is
# (server_id, binary_name, adapter_module, adapter_class). Kept in
# sync with ``PythonStrategy.SERVER_SET`` (Stage 1E §14.1).
_PYTHON_SERVERS: tuple[tuple[str, str, str, str], ...] = (
    (
        "pylsp-rope",
        "pylsp",
        "solidlsp.language_servers.pylsp_server",
        "PylspServer",
    ),
    (
        "basedpyright",
        "basedpyright-langserver",
        "solidlsp.language_servers.basedpyright_server",
        "BasedpyrightServer",
    ),
    (
        "ruff",
        "ruff",
        "solidlsp.language_servers.ruff_server",
        "RuffServer",
    ),
)


def _build_python_server(adapter_module: str, adapter_class: str, root: Path) -> Any:
    """Instantiate a Stage 1E Python LSP adapter directly.

    Mirrors ``conftest._build_python_server`` so this test is independent
    of test/integration fixtures.
    """
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    cls = getattr(import_module(adapter_module), adapter_class)
    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    return cls(cfg, str(root), SolidLSPSettings())


def _xfail_if_any_binary_missing() -> None:
    """``xfail`` (not ``skip``) per spec when any LSP binary is unavailable.

    Per spec self-review checklist: a partial dev environment must surface
    as an expected failure, not a silent skip — silent skips erode the
    parallelism-evidence guarantee this test is meant to provide.
    """
    missing = [
        binary for _, binary, *_ in _PYTHON_SERVERS if shutil.which(binary) is None
    ]
    if missing:
        pytest.xfail(
            f"Python LSP binaries not on PATH: {missing}. "
            f"This test requires all three booted to prove parallelism."
        )


@pytest.mark.python
@pytest.mark.asyncio
async def test_broadcast_runs_three_python_servers_in_parallel(
    calcpy_workspace: Path,
) -> None:
    """`broadcast` must finish faster than the sum of per-server timings.

    Boots pylsp + basedpyright + ruff against the calcpy fixture, wraps
    each in ``_AsyncAdapter``, and times a ``textDocument/codeAction``
    broadcast vs the sum of the same call against each server in series.
    """
    _xfail_if_any_binary_missing()

    # Boot all three LSPs sequentially. Each ``start_server()`` is a
    # sync context manager (see ``solidlsp/ls.py:717``); ``ExitStack``
    # tears them down at the end of the ``with`` block.
    from contextlib import ExitStack

    servers: dict[str, Any] = {}
    with ExitStack() as stack:
        for server_id, _, adapter_module, adapter_class in _PYTHON_SERVERS:
            srv = _build_python_server(adapter_module, adapter_class, calcpy_workspace)
            stack.enter_context(srv.start_server())
            servers[server_id] = srv

        assert set(servers) == {"pylsp-rope", "basedpyright", "ruff"}, (
            f"expected three Python servers booted; got {set(servers)}"
        )

        # Give each LSP a moment to settle (mirrors smoke-test cadence).
        time.sleep(0.5)

        # Open the target file on each server so request_code_actions has
        # a synced document to reason about.
        target_rel = "calcpy/core.py"
        target_abs = str(calcpy_workspace / target_rel)
        assert Path(target_abs).is_file(), f"fixture file missing: {target_abs}"

        # ``open_file`` is a context manager on SolidLanguageServer. Hold
        # all three open across both timing windows.
        for srv in servers.values():
            stack.enter_context(srv.open_file(target_rel))
        time.sleep(0.5)

        # Wrap each adapter — this is the production wiring at
        # ``scalpel_runtime._spawn_*``. Without the wrapper the
        # `MultiServerCoordinator.__init__` validation (commit 03b)
        # would raise TypeError before we even get here.
        coord = MultiServerCoordinator(
            servers={sid: _AsyncAdapter(srv) for sid, srv in servers.items()}
        )

        broadcast_kwargs: dict[str, Any] = {
            "file": target_abs,
            "start": {"line": 0, "character": 0},
            "end": {"line": 10_000, "character": 0},
            "only": ["source.organizeImports"],
            "diagnostics": [],
        }

        # ----- Warm-up: amortise per-server first-call indexing cost. -----
        # basedpyright in particular kicks off a workspace index on first
        # codeAction request; if that first call lands inside the timing
        # window the comparison is dominated by indexing, not parallelism.
        await coord.broadcast(
            method="textDocument/codeAction",
            kwargs=broadcast_kwargs,
            timeout_ms=10_000,
        )
        for srv in servers.values():
            await asyncio.to_thread(
                srv.request_code_actions,
                target_abs,
                {"line": 0, "character": 0},
                {"line": 10_000, "character": 0},
                ["source.organizeImports"],
                2,
                [],
            )

        # ----- Measurement -----
        # N=20 iterations amortises asyncio scheduling overhead at the
        # μs scale relative to the per-call work at the ms scale. With
        # 3 servers × 20 iterations × ~2-5 ms each, the serial total
        # lands near 120-300 ms and the parallel total near 50-120 ms,
        # well above scheduling-noise resolution.
        n_iters = 20

        # Parallel timing.
        t0 = time.perf_counter()
        last_result = None
        for _ in range(n_iters):
            last_result = await coord.broadcast(
                method="textDocument/codeAction",
                kwargs=broadcast_kwargs,
                timeout_ms=10_000,
            )
        parallel_elapsed = time.perf_counter() - t0
        result = last_result

        # Serial timing — call each underlying sync server in turn.
        # ``await asyncio.to_thread`` matches what ``_AsyncAdapter`` does
        # internally so the comparison is apples-to-apples (we're NOT
        # comparing async-await overhead to sync-call overhead).
        per_server_totals: dict[str, float] = {sid: 0.0 for sid in servers}
        s_t0 = time.perf_counter()
        for _ in range(n_iters):
            for sid, srv in servers.items():
                ss0 = time.perf_counter()
                await asyncio.to_thread(
                    srv.request_code_actions,
                    target_abs,
                    {"line": 0, "character": 0},
                    {"line": 10_000, "character": 0},
                    ["source.organizeImports"],
                    2,
                    [],
                )
                per_server_totals[sid] += time.perf_counter() - ss0
        serial_total = time.perf_counter() - s_t0

    # Outside the ExitStack — servers are torn down. Now make the assertions
    # so any failure message includes the timing context, not a teardown
    # exception.

    # Sanity: at least one server answered on the final iteration.
    assert result is not None and result.responses, (
        f"broadcast returned no responses; "
        f"errors={getattr(result, 'errors', None)!r} "
        f"timeouts={[t.model_dump() for t in getattr(result, 'timeouts', [])]!r}"
    )

    # Parallelism evidence — the headline guarantee.
    #
    # In stage-v0.2.0-review-m9 the single Amdahl-aware budget was SPLIT
    # into two narrower assertions, each catching a distinct regression
    # mode. The original combined ``parallel < 0.9*serial + 0.1*max_single``
    # accepted runs that captured as little as 2% real save, masking
    # subtle parallelism degradation behind the Amdahl floor.
    #
    # Both assertions must pass for the test to pass.
    #
    # ----- Assertion 1: regression detector -----
    #
    # Catches "broadcast collapsed back to serial round-robin" — the
    # historical TypeError-on-await failure mode and any future
    # equivalent. Threshold: parallel must be at least 5% faster than
    # serial. A round-robin regression saves exactly 0% (modulo
    # noise), so 5% cleanly separates real parallelism from sequential
    # execution.
    max_single_server = max(per_server_totals.values())
    serial_regression_budget = serial_total * 0.95
    assert parallel_elapsed < serial_regression_budget, (
        f"REGRESSION DETECTOR: broadcast collapsed to serial round-robin: "
        f"parallel={parallel_elapsed:.3f}s "
        f"vs serial={serial_total:.3f}s "
        f"vs 95%-of-serial budget={serial_regression_budget:.3f}s "
        f"(parallel must save >=5% vs serial; got "
        f"{(serial_total - parallel_elapsed) / serial_total:.1%}) "
        f"per_server={ {k: round(v, 3) for k, v in per_server_totals.items()} }"
    )

    # ----- Assertion 2: parallelism-quality detector -----
    #
    # Catches "parallelism degraded to glorified round-robin" — broadcast
    # is faster than serial but well above ``max_single``, indicating the
    # fan-out is dispatching but the scheduler is not actually overlapping
    # the per-server work. Amdahl's law floors the parallel time at
    # ``max_single``; we allow up to 50ms of asyncio + thread-pool
    # scheduling overhead on top of that floor.
    #
    # Why 50ms and not the original 10% slack? With three Python LSPs and
    # N=20 iterations, asyncio task-creation + thread-pool dispatch costs
    # roughly 1-3ms per iteration, so 50ms absorbs ~15-50× the median
    # scheduling cost — generous enough to absorb mixed-suite jitter while
    # still catching a degradation that pushes parallel time toward the
    # 10-20% above-Amdahl-floor regime.
    parallelism_quality_budget = max_single_server + 0.050
    assert parallel_elapsed < parallelism_quality_budget, (
        f"PARALLELISM DEGRADED: broadcast wall-time well above the "
        f"Amdahl floor of max(per_server_total): "
        f"parallel={parallel_elapsed:.3f}s "
        f"vs max_single={max_single_server:.3f}s "
        f"vs floor+50ms budget={parallelism_quality_budget:.3f}s "
        f"(real parallelism should land within 50ms of max_single; "
        f"current overshoot suggests round-robin-with-extra-steps) "
        f"serial={serial_total:.3f}s "
        f"per_server={ {k: round(v, 3) for k, v in per_server_totals.items()} }"
    )

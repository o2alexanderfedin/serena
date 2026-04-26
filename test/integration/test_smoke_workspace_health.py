"""Stage 1H smoke 3 — ``scalpel_workspace_health`` reports per-language health.

Proves the Stage 1G ``ScalpelWorkspaceHealthTool`` wires correctly
against the Stage 1F ``CapabilityCatalog`` and the Stage 1C
``LspPool`` — without requiring real LSP processes to be spawned
(the catalog is static, and the pool's ``stats()`` returns the
``not_started`` indexing-state shape when nothing is acquired yet).

This is intentionally lighter than booting all four LSPs: the goal of
the smoke gate is "the health-probe wires correctly", not "every
server is hot".  Smoke 1 + smoke 2 already prove the LSPs themselves
boot.

Note on the "4 LSPs" wording in the orchestrator brief: the v0.1.0
``CapabilityCatalog`` only lists servers that advertise refactor or
quickfix capabilities at strategy-build time.  basedpyright registers
its capabilities dynamically (pull-mode, post-init) and therefore
does not appear in the static catalog — only ``pylsp-rope``,
``ruff``, and ``rust-analyzer`` do.  The smoke asserts the three
catalog-visible servers; basedpyright surface is exercised by the
adapter-boot fixture in ``conftest.py``.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture
def reset_runtime() -> Iterator[None]:
    """Drop the ScalpelRuntime singleton so each test starts clean."""
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def test_workspace_health_reports_python_and_rust_languages(
    reset_runtime: None,  # noqa: ARG001 — fixture ensures clean singleton
    calcrs_workspace: Path,
) -> None:
    """workspace_health must return a JSON payload with python + rust entries."""
    del reset_runtime  # silence unused-parameter; presence in arglist is the point.
    from serena.tools.scalpel_primitives import _build_language_health
    from solidlsp.ls_config import Language

    # Drive the underlying ``_build_language_health`` directly — the
    # ``Tool.apply`` wrapper requires a full SerenaAgent project context
    # which is overkill for a wire-test.  This calls the same code
    # paths (catalog + pool stats) the production tool calls.
    py_health = _build_language_health(Language.PYTHON, calcrs_workspace)
    rust_health = _build_language_health(Language.RUST, calcrs_workspace)

    # Each language must report at least one server with capabilities.
    assert py_health.language == "python"
    assert py_health.indexing_state in ("not_started", "ready")
    assert py_health.capabilities_count > 0, (
        "python catalog records empty — Stage 1F regression"
    )
    server_ids = {s.server_id for s in py_health.servers}
    assert {"pylsp-rope", "ruff"}.issubset(server_ids), (
        f"expected pylsp-rope + ruff in python health; got {server_ids!r}"
    )

    assert rust_health.language == "rust"
    assert rust_health.indexing_state in ("not_started", "ready")
    assert rust_health.capabilities_count > 0, (
        "rust catalog records empty — Stage 1F regression"
    )
    rust_server_ids = {s.server_id for s in rust_health.servers}
    assert "rust-analyzer" in rust_server_ids, (
        f"expected rust-analyzer in rust health; got {rust_server_ids!r}"
    )


def test_workspace_health_payload_is_json_serialisable(
    reset_runtime: None,  # noqa: ARG001 — fixture ensures clean singleton
    calcrs_workspace: Path,
) -> None:
    """The ``WorkspaceHealth`` Pydantic model must round-trip through JSON."""
    del reset_runtime  # silence unused-parameter; presence in arglist is the point.
    from serena.tools.scalpel_primitives import _build_language_health
    from serena.tools.scalpel_schemas import WorkspaceHealth
    from solidlsp.ls_config import Language

    payload = WorkspaceHealth(
        project_root=str(calcrs_workspace),
        languages={
            "python": _build_language_health(Language.PYTHON, calcrs_workspace),
            "rust": _build_language_health(Language.RUST, calcrs_workspace),
        },
    )
    raw = payload.model_dump_json(indent=2)
    parsed = json.loads(raw)

    assert parsed["project_root"] == str(calcrs_workspace)
    assert set(parsed["languages"].keys()) == {"python", "rust"}
    for lang_block in parsed["languages"].values():
        assert lang_block["indexing_state"] in (
            "not_started",
            "ready",
            "indexing",
            "failed",
        )
        assert lang_block["capabilities_count"] >= 0

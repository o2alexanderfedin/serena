from __future__ import annotations

from pathlib import Path

from serena.tools.scalpel_primitives import _build_language_health
from serena.tools.scalpel_runtime import ScalpelRuntime
from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry
from solidlsp.ls_config import Language


def test_build_language_health_surfaces_dynamic_capabilities(tmp_path: Path) -> None:
    """`_build_language_health` must surface registry contents into
    LanguageHealth.dynamic_capabilities and add them to capabilities_count.

    Source-server attribution: the runtime catalog's python records
    declare ``pylsp-rope`` and ``ruff`` as their ``source_server`` values
    (basedpyright is documented in ProvenanceLiteral but does not
    contribute records at MVP — see serena.refactoring.multi_server).
    Registering a dynamic method under any active python source_server
    therefore unions into the python LanguageHealth. We use
    ``pylsp-rope`` here because it is an actual python source_server
    in the runtime catalog.
    """
    ScalpelRuntime.reset_for_testing()
    try:
        registry = DynamicCapabilityRegistry()
        registry.register("pylsp-rope", "wh-reg-1", "textDocument/publishDiagnostics")
        registry.register("pylsp-rope", "wh-reg-2", "textDocument/codeAction")
        # A registration against an unknown server-id MUST be ignored —
        # only ids that intersect the static catalog count for this
        # language.
        registry.register("rust-analyzer", "wh-reg-3", "textDocument/hover")

        health = _build_language_health(
            Language.PYTHON,
            tmp_path,
            dynamic_registry=registry,
        )

        assert "textDocument/publishDiagnostics" in health.dynamic_capabilities
        assert "textDocument/codeAction" in health.dynamic_capabilities
        # rust-analyzer does NOT belong to python's source_server set, so
        # its registration must not leak into the python LanguageHealth.
        assert "textDocument/hover" not in health.dynamic_capabilities
        # Static + 2 unioned dynamic methods.
        assert health.capabilities_count >= 2
    finally:
        ScalpelRuntime.reset_for_testing()


def test_build_language_health_default_no_dynamic(tmp_path: Path) -> None:
    """Without a registry, dynamic_capabilities is empty and
    capabilities_count is purely the static catalog count (regression
    guard for the optional-parameter contract)."""
    ScalpelRuntime.reset_for_testing()
    try:
        health = _build_language_health(Language.PYTHON, tmp_path)
        assert health.dynamic_capabilities == ()
    finally:
        ScalpelRuntime.reset_for_testing()

"""Stream 6 / Leaf D — JavaStrategy unit tests.

Mirrors ``test_cpp_strategy.py``: identity constants, Protocol
conformance, single-server build, and registry membership. The strategy
is single-LSP (no multi-server merge for Java — jdtls is canonical),
so ``build_servers`` returns exactly one entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_java_strategy_imports() -> None:
    from serena.refactoring.java_strategy import JavaStrategy

    del JavaStrategy  # import-success is the assertion


def test_java_strategy_is_a_language_strategy() -> None:
    from serena.refactoring.java_strategy import JavaStrategy
    from serena.refactoring.language_strategy import LanguageStrategy

    assert isinstance(JavaStrategy(pool=MagicMock()), LanguageStrategy)


def test_java_identity_constants() -> None:
    from serena.refactoring.java_strategy import JavaStrategy

    s = JavaStrategy(pool=MagicMock())
    assert s.language_id == "java"
    # Standard Java source.
    assert ".java" in s.extension_allow_list
    # No unrelated suffixes.
    assert ".py" not in s.extension_allow_list
    assert ".rs" not in s.extension_allow_list
    assert ".ts" not in s.extension_allow_list
    assert ".go" not in s.extension_allow_list
    assert ".cpp" not in s.extension_allow_list
    assert ".md" not in s.extension_allow_list


def test_java_code_action_allow_list_covers_jdtls_kinds() -> None:
    """The allow-list must cover the jdtls advertised code action kinds."""
    from serena.refactoring.java_strategy import JavaStrategy

    s = JavaStrategy(pool=MagicMock())
    # Import management.
    assert "source.organizeImports" in s.code_action_allow_list
    # Code generation.
    assert "source.generate.constructor" in s.code_action_allow_list
    assert "source.generate.hashCodeEquals" in s.code_action_allow_list
    assert "source.generate.toString" in s.code_action_allow_list
    assert "source.generate.accessors" in s.code_action_allow_list
    assert "source.generate.overrideMethods" in s.code_action_allow_list
    assert "source.generate.delegateMethods" in s.code_action_allow_list
    # Extract refactors.
    assert "refactor.extract" in s.code_action_allow_list
    assert "refactor.extract.method" in s.code_action_allow_list
    assert "refactor.extract.variable" in s.code_action_allow_list
    assert "refactor.extract.field" in s.code_action_allow_list
    assert "refactor.extract.interface" in s.code_action_allow_list
    # Inline refactors.
    assert "refactor.inline" in s.code_action_allow_list
    # Rewrite refactors.
    assert "refactor.rewrite" in s.code_action_allow_list
    # Quick-fix.
    assert "quickfix" in s.code_action_allow_list
    # Generic refactor parent kind.
    assert "refactor" in s.code_action_allow_list


def test_execute_command_whitelist_is_empty() -> None:
    """jdtls does not expose workspace/executeCommand verbs from the strategy layer."""
    from serena.refactoring.java_strategy import JavaStrategy

    assert JavaStrategy.execute_command_whitelist() == frozenset()


def test_build_servers_returns_single_jdtls_entry() -> None:
    from serena.refactoring.java_strategy import JavaStrategy
    from serena.refactoring.lsp_pool import LspPoolKey

    fake_server = MagicMock(name="jdtls-server")
    pool = MagicMock()
    pool.acquire.return_value = fake_server

    strat = JavaStrategy(pool=pool)
    out = strat.build_servers(Path("/tmp/some-java-project"))

    assert set(out.keys()) == {"jdtls"}
    assert out["jdtls"] is fake_server
    pool.acquire.assert_called_once()
    key = pool.acquire.call_args.args[0]
    assert isinstance(key, LspPoolKey)
    assert key.language == "java"


def test_strategy_registry_includes_java() -> None:
    """STRATEGY_REGISTRY[Language.JAVA] must resolve to JavaStrategy."""
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.java_strategy import JavaStrategy
    from solidlsp.ls_config import Language

    assert Language.JAVA in STRATEGY_REGISTRY
    assert STRATEGY_REGISTRY[Language.JAVA] is JavaStrategy


def test_provenance_literal_includes_jdtls() -> None:
    """ProvenanceLiteral must include 'jdtls' for catalog attribution."""
    from typing import get_args

    from serena.refactoring.multi_server import ProvenanceLiteral

    assert "jdtls" in get_args(ProvenanceLiteral)


def test_default_source_server_by_language_includes_java() -> None:
    """_DEFAULT_SOURCE_SERVER_BY_LANGUAGE must have a 'java' → 'jdtls' entry."""
    from serena.refactoring.capabilities import _DEFAULT_SOURCE_SERVER_BY_LANGUAGE  # pyright: ignore[reportPrivateUsage]

    assert _DEFAULT_SOURCE_SERVER_BY_LANGUAGE.get("java") == "jdtls"


def test_adapter_map_includes_jdtls() -> None:
    """_adapter_map() must return a 'jdtls' → JdtlsServer mapping."""
    from serena.refactoring.capabilities import _adapter_map  # pyright: ignore[reportPrivateUsage]
    from solidlsp.language_servers.jdtls_server import JdtlsServer

    assert _adapter_map().get("jdtls") is JdtlsServer


def test_adapter_attribution_order_includes_java() -> None:
    """_ADAPTER_ATTRIBUTION_ORDER must have a 'java' entry with ('jdtls',)."""
    from serena.refactoring.capabilities import _ADAPTER_ATTRIBUTION_ORDER  # pyright: ignore[reportPrivateUsage]

    assert _ADAPTER_ATTRIBUTION_ORDER.get("java") == ("jdtls",)


def test_installer_registry_includes_java() -> None:
    """_installer_registry() must map 'java' → JdtlsInstaller."""
    from serena.installer.jdtls_installer import JdtlsInstaller
    from serena.tools.scalpel_primitives import _installer_registry  # pyright: ignore[reportPrivateUsage]

    assert _installer_registry().get("java") is JdtlsInstaller


# ---------------------------------------------------------------------------
# v1.5 Phase 2 — extended allow list for extract Java arm + new
# constructor / overrideMethods facades.
# ---------------------------------------------------------------------------


def test_java_allow_list_includes_extract_function_and_constant() -> None:
    """v1.5 P2 — `refactor.extract.function` and `refactor.extract.constant`
    must be in the allow list so the existing ``ExtractTool`` can
    dispatch ``target="function"`` and ``target="constant"`` against jdtls
    via LSP §3.18.1 prefix matching against ``refactor.extract.method``.
    """
    from serena.refactoring.java_strategy import JavaStrategy

    s = JavaStrategy(pool=MagicMock())
    assert "refactor.extract.function" in s.code_action_allow_list
    assert "refactor.extract.constant" in s.code_action_allow_list
    # variable already present, but assert again for completeness:
    assert "refactor.extract.variable" in s.code_action_allow_list


def test_kind_to_facade_jdtls_extract_family() -> None:
    """v1.5 P2 — KIND_TO_FACADE must route ``("jdtls", "refactor.extract")``
    to ``"extract"`` (family-level catalog routing-hint, mirroring
    the rust-analyzer + pylsp-rope rows shipped in P1).
    """
    from serena.refactoring.capabilities import KIND_TO_FACADE

    assert KIND_TO_FACADE.get(("jdtls", "refactor.extract")) == "extract"


def test_kind_to_facade_jdtls_generate_constructor() -> None:
    """v1.5 P2 — KIND_TO_FACADE must route the jdtls source.generate.constructor
    family entry to the new ``generate_constructor`` facade.
    """
    from serena.refactoring.capabilities import KIND_TO_FACADE

    assert (
        KIND_TO_FACADE.get(("jdtls", "source.generate.constructor"))
        == "generate_constructor"
    )


def test_kind_to_facade_jdtls_override_methods() -> None:
    """v1.5 P2 — KIND_TO_FACADE must route the jdtls
    source.generate.overrideMethods family entry to the new
    ``override_methods`` facade.
    """
    from serena.refactoring.capabilities import KIND_TO_FACADE

    assert (
        KIND_TO_FACADE.get(("jdtls", "source.generate.overrideMethods"))
        == "override_methods"
    )


# ---------------------------------------------------------------------------
# v1.5 Phase 2 — ExtractTool Java arm dispatch + invalid-combo gate.
# ---------------------------------------------------------------------------


def test_extract_java_arm_dispatches_against_jdtls(tmp_path: Path) -> None:
    """v1.5 P2 — ``ExtractTool(language="java", target="function")``
    routes to the jdtls coordinator and dispatches a
    ``refactor.extract.function`` codeAction (jdtls's
    ``refactor.extract.method`` matches via LSP §3.18.1 prefix rule).
    """
    import json
    from unittest.mock import patch

    from serena.tools.scalpel_facades import ExtractTool
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    target = tmp_path / "Foo.java"
    target.write_text("class Foo { void bar() { int x = 1 + 2; } }\n")
    tool = ExtractTool.__new__(ExtractTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    fake_coord = MagicMock()
    seen: dict[str, object] = {}

    async def _merge(**kwargs: object) -> list[MagicMock]:
        seen["only"] = kwargs["only"]
        return [
            MagicMock(
                action_id="jdtls:1",
                title="Extract method",
                kind="refactor.extract.method",
                provenance="jdtls",
            )
        ]

    fake_coord.merge_code_actions = _merge

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ) as patched:
        out = tool.apply(
            file=str(target),
            range={
                "start": {"line": 0, "character": 25},
                "end": {"line": 0, "character": 38},
            },
            target="function",
            new_name="extracted",
            language="java",
        )

    payload = json.loads(out)
    assert payload["applied"] is True, payload
    # The dispatcher resolved a Java coordinator:
    assert patched.call_args.kwargs["language"] == "java"
    # The kind requested was the function-family kind (LSP prefix-matches the method kind):
    assert seen["only"] == ["refactor.extract.function"]


def test_extract_java_arm_invalid_target_module_returns_capability_not_available(
    tmp_path: Path,
) -> None:
    """v1.5 P2 — ``(language="java", target="module")`` is invalid per the
    §4.2.1 target-validity matrix and must short-circuit with a
    CAPABILITY_NOT_AVAILABLE skip envelope before any LSP call.
    """
    import json
    from unittest.mock import patch

    from serena.tools.scalpel_facades import ExtractTool
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    target = tmp_path / "Foo.java"
    target.write_text("class Foo {}\n")
    tool = ExtractTool.__new__(ExtractTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    fake_coord = MagicMock()
    fake_coord.merge_code_actions = MagicMock()

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            range={
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 12},
            },
            target="module",
            language="java",
        )

    payload = json.loads(out)
    assert payload["status"] == "skipped"
    assert "lsp_does_not_support_" in payload["reason"]
    assert payload["language"] == "java"
    fake_coord.merge_code_actions.assert_not_called()


def test_extract_java_arm_invalid_target_type_alias_returns_capability_not_available(
    tmp_path: Path,
) -> None:
    """v1.5 P2 — ``(language="java", target="type_alias")`` is invalid per
    the §4.2.1 target-validity matrix (Java has no type alias) and must
    short-circuit with a CAPABILITY_NOT_AVAILABLE skip envelope.
    """
    import json
    from unittest.mock import patch

    from serena.tools.scalpel_facades import ExtractTool
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    target = tmp_path / "Foo.java"
    target.write_text("class Foo {}\n")
    tool = ExtractTool.__new__(ExtractTool)
    tool.get_project_root = lambda: str(tmp_path)  # type: ignore[method-assign]

    fake_coord = MagicMock()
    fake_coord.merge_code_actions = MagicMock()

    with patch(
        "serena.tools.scalpel_facades.coordinator_for_facade",
        return_value=fake_coord,
    ):
        out = tool.apply(
            file=str(target),
            range={
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 12},
            },
            target="type_alias",
            language="java",
        )

    payload = json.loads(out)
    assert payload["status"] == "skipped"
    assert payload["language"] == "java"
    fake_coord.merge_code_actions.assert_not_called()

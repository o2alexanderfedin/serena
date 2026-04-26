"""T1 — LanguageStrategy Protocol + Rust/Python extension mixins."""

from __future__ import annotations

import inspect


def test_language_strategy_protocol_imports() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy

    del LanguageStrategy  # import-success is the assertion


def test_language_strategy_required_methods() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy

    required = {"language_id", "extension_allow_list", "code_action_allow_list", "build_servers"}
    members = {name for name, _ in inspect.getmembers(LanguageStrategy)}
    missing = required - members
    assert not missing, f"LanguageStrategy missing required members: {missing}"


def test_rust_extensions_carry_assist_whitelist() -> None:
    from serena.refactoring.language_strategy import RustStrategyExtensions

    assist = RustStrategyExtensions.ASSIST_FAMILY_WHITELIST
    assert isinstance(assist, frozenset)
    # rust-analyzer assist kinds use the "refactor.<sub>.assist" hierarchy.
    assert any(k.startswith("refactor.") for k in assist), assist
    assert "refactor.extract" in assist or "refactor.extract.assist" in assist


def test_python_extensions_carry_three_server_set() -> None:
    from serena.refactoring.language_strategy import PythonStrategyExtensions

    assert PythonStrategyExtensions.SERVER_SET == ("pylsp-rope", "basedpyright", "ruff")
    # P5a: pylsp-mypy MUST NOT be in the active server set.
    assert "pylsp-mypy" not in PythonStrategyExtensions.SERVER_SET


def test_protocol_runtime_checkable_against_a_dummy() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy

    class _Dummy:
        language_id = "dummy"
        extension_allow_list = frozenset({".dum"})
        code_action_allow_list = frozenset({"refactor"})

        def build_servers(self, project_root):  # type: ignore[no-untyped-def]
            del project_root
            return {}

    # Protocol must be @runtime_checkable so isinstance works.
    assert isinstance(_Dummy(), LanguageStrategy)

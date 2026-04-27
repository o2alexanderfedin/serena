"""v1.1 Stream 5 / Leaf 07 Task 2 — `scalpel_annotate_return_type` tests.

The helper queries basedpyright via ``textDocument/inlayHint``. On the
host CI (no booted basedpyright) we inject a stub
``inlay_hint_provider`` callable so the apply-path is exercised
end-to-end without spinning up the LSP. Real wire-up to a live
basedpyright is exercised in the e2e suite.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from serena.tools import scalpel_facades as facades_mod
from serena.tools.scalpel_facades import ScalpelAnnotateReturnTypeTool
from serena.tools.scalpel_runtime import ScalpelRuntime
from serena.tools.tools_base import Tool
from serena.util.inspection import iter_subclasses


@pytest.fixture(autouse=True)
def _reset_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    monkeypatch.setenv("O2_SCALPEL_CACHE", str(tmp_path / "cache"))
    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool(tmp_path: Path) -> ScalpelAnnotateReturnTypeTool:
    agent = MagicMock(name="SerenaAgent")
    agent.get_project_root.return_value = str(tmp_path)
    tool = ScalpelAnnotateReturnTypeTool(agent=agent)
    object.__setattr__(tool, "get_project_root", lambda: str(tmp_path))
    return tool


def _patch_provider(
    monkeypatch: pytest.MonkeyPatch,
    label: str | None,
) -> None:
    """Stub ``_get_inlay_hint_provider`` so tests don't need a live basedpyright.

    A ``label`` of ``None`` means "no provider available" — the helper
    short-circuits with the ``basedpyright_unavailable`` discriminator.
    Otherwise the stub returns one inlay hint shaped like the real
    basedpyright payload (``{'label': '-> int', 'kind': 1, ...}``).
    """
    if label is None:
        monkeypatch.setattr(
            facades_mod, "_get_inlay_hint_provider", lambda _project_root: None,
        )
        return

    def fake_provider(_uri: str, _range: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "position": {"line": 0, "character": 9},
                "label": label,
                "kind": 1,
                "paddingLeft": True,
            },
        ]

    monkeypatch.setattr(
        facades_mod, "_get_inlay_hint_provider", lambda _project_root: fake_provider,
    )


# ---------------------------------------------------------------------------
# Step 2.1 — happy path (basedpyright stub returns "-> int")
# ---------------------------------------------------------------------------


def test_annotate_return_type_inserts_inferred_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "a.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    _patch_provider(monkeypatch, "-> int")
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="a.py", symbol="two", allow_out_of_workspace=True),
    )
    assert payload["applied"] is True
    after = (tmp_path / "a.py").read_text(encoding="utf-8")
    assert "def two() -> int:" in after
    assert payload["language_options"]["inferred_type"] == "int"


# ---------------------------------------------------------------------------
# Step 2.4 — already annotated -> skipped (no edit, reason carried)
# ---------------------------------------------------------------------------


def test_annotate_return_type_skips_already_annotated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = "def two() -> int:\n    return 2\n"
    (tmp_path / "a.py").write_text(src, encoding="utf-8")
    _patch_provider(monkeypatch, "-> int")
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="a.py", symbol="two", allow_out_of_workspace=True),
    )
    assert payload["applied"] is False
    assert payload["no_op"] is True
    assert payload["language_options"]["status"] == "skipped"
    assert payload["language_options"]["reason"] == "already_annotated"
    # File must not change.
    assert (tmp_path / "a.py").read_text(encoding="utf-8") == src


# ---------------------------------------------------------------------------
# Provider-unavailable path — basedpyright not booted on host
# ---------------------------------------------------------------------------


def test_annotate_return_type_skips_when_basedpyright_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "a.py").write_text("def two():\n    return 2\n", encoding="utf-8")
    _patch_provider(monkeypatch, None)
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="a.py", symbol="two", allow_out_of_workspace=True),
    )
    assert payload["applied"] is False
    assert payload["language_options"]["reason"] == "basedpyright_unavailable"


def test_annotate_return_type_skips_when_no_inferable_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """basedpyright returns no Type-kind inlay hint -> ``no_inferable_type``."""
    (tmp_path / "a.py").write_text("def two():\n    return 2\n", encoding="utf-8")

    def empty_provider(_uri: str, _range: dict[str, Any]) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(
        facades_mod,
        "_get_inlay_hint_provider",
        lambda _project_root: empty_provider,
    )
    tool = _build_tool(tmp_path)

    payload = json.loads(
        tool.apply(file="a.py", symbol="two", allow_out_of_workspace=True),
    )
    assert payload["applied"] is False
    assert payload["language_options"]["reason"] == "no_inferable_type"


# ---------------------------------------------------------------------------
# Auto-registration / naming
# ---------------------------------------------------------------------------


def test_annotate_return_type_tool_appears_in_iter_subclasses() -> None:
    discovered = {cls.get_name_from_cls() for cls in iter_subclasses(Tool)}
    assert "scalpel_annotate_return_type" in discovered


def test_annotate_return_type_tool_class_name_is_snake_cased() -> None:
    assert (
        ScalpelAnnotateReturnTypeTool.get_name_from_cls()
        == "scalpel_annotate_return_type"
    )

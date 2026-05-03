"""T3 — CapabilityDescribeTool: full descriptor + unknown-id failure."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    ScalpelRuntime.reset_for_testing()
    yield
    ScalpelRuntime.reset_for_testing()


def _build_tool():  # type: ignore[no-untyped-def]
    from unittest.mock import MagicMock

    from serena.tools.scalpel_primitives import CapabilityDescribeTool

    agent = MagicMock(name="SerenaAgent")
    return CapabilityDescribeTool(agent=agent)


def _pick_a_real_capability_id() -> str:
    from serena.tools.scalpel_runtime import ScalpelRuntime

    cat = ScalpelRuntime.instance().catalog()
    if not cat.records:
        pytest.skip("Capability catalog is empty in this build; nothing to describe.")
    return cat.records[0].id


def test_tool_name_is_scalpel_capability_describe() -> None:
    from serena.tools.scalpel_primitives import CapabilityDescribeTool

    assert CapabilityDescribeTool.get_name_from_cls() == "capability_describe"


def test_apply_returns_full_descriptor_for_known_id() -> None:
    tool = _build_tool()
    cid = _pick_a_real_capability_id()
    raw = tool.apply(capability_id=cid)
    payload = json.loads(raw)
    assert payload["capability_id"] == cid
    assert set(payload).issuperset({
        "capability_id", "title", "language", "kind",
        "source_server", "preferred_facade",
        "params_schema", "extension_allow_list", "description",
    })


def test_apply_unknown_id_returns_failure_payload() -> None:
    tool = _build_tool()
    raw = tool.apply(capability_id="not.a.real.capability")
    payload = json.loads(raw)
    assert "failure" in payload
    assert payload["failure"]["code"] == "CAPABILITY_NOT_AVAILABLE"
    assert "candidates" in payload["failure"]

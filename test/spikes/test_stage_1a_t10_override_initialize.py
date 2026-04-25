"""T10 - override_initialize_params hook.

Default is identity (returns params unchanged). Subclasses (T13 will wire
RustAnalyzerLanguageServer) override to inject capability tweaks like
experimental.snippetTextEdit=False per Phase 0 S2.
"""

from __future__ import annotations

import pytest

from solidlsp.ls import SolidLanguageServer


def test_default_override_returns_params_unchanged(slim_sls: SolidLanguageServer) -> None:
    p = {"capabilities": {"a": 1}, "rootUri": "file:///tmp"}
    out = slim_sls.override_initialize_params(p)
    assert out == p


def test_default_override_returns_same_object_or_equal_dict(slim_sls: SolidLanguageServer) -> None:
    """Default impl is allowed to return the same object OR a shallow copy. Either is fine
    as long as the shape is unchanged."""
    p: dict = {"capabilities": {}}
    out = slim_sls.override_initialize_params(p)
    assert out == p


def test_subclass_can_inject_capability(slim_sls: SolidLanguageServer, monkeypatch: pytest.MonkeyPatch) -> None:
    def my_override(params: dict) -> dict:
        params.setdefault("capabilities", {}).setdefault("experimental", {})["snippetTextEdit"] = False
        return params

    monkeypatch.setattr(slim_sls, "override_initialize_params", my_override)
    out = slim_sls.override_initialize_params({})
    assert out["capabilities"]["experimental"]["snippetTextEdit"] is False

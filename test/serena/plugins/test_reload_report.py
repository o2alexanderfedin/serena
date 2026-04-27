"""Stream 5 / Leaf 03 Task 1 — ``ReloadReport`` pydantic model tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from serena.plugins.reload_report import ReloadReport


def test_reload_report_minimal() -> None:
    r = ReloadReport(added=("rust",), removed=(), unchanged=("python",), errors=())
    assert r.added == ("rust",)
    assert r.removed == ()
    assert r.unchanged == ("python",)
    assert r.errors == ()
    assert r.is_clean is True


def test_reload_report_errors_mark_unclean() -> None:
    r = ReloadReport(
        added=(),
        removed=(),
        unchanged=(),
        errors=(("kotlin", "missing plugin.json"),),
    )
    assert r.is_clean is False
    assert r.errors == (("kotlin", "missing plugin.json"),)


def test_reload_report_is_frozen() -> None:
    r = ReloadReport(added=(), removed=(), unchanged=("rust",), errors=())
    with pytest.raises(ValidationError):
        r.added = ("python",)  # type: ignore[misc]


def test_reload_report_rejects_unknown_field() -> None:
    # ``unexpected`` is passed via ``**kwargs`` so static type checkers
    # don't flag the deliberately-bad keyword (pydantic's ``extra="forbid"``
    # is what's under test here, not the type checker).
    bad_kwargs: dict[str, object] = {
        "added": (),
        "removed": (),
        "unchanged": (),
        "errors": (),
        "unexpected": "boom",
    }
    with pytest.raises(ValidationError):
        ReloadReport(**bad_kwargs)  # type: ignore[arg-type]


def test_reload_report_serialises_with_is_clean() -> None:
    r = ReloadReport(added=("rust",), removed=(), unchanged=(), errors=())
    payload = r.model_dump(mode="json")
    assert payload["added"] == ["rust"]
    assert payload["is_clean"] is True

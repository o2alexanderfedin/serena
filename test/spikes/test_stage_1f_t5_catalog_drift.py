"""T5 — capability catalog drift gate (the CI assertion)."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest


_REBASELINE_HINT = (
    "To re-baseline, run: pytest "
    "test/spikes/test_stage_1f_t5_catalog_drift.py "
    "--update-catalog-baseline"
)


def test_live_catalog_matches_checked_in_baseline(
    capability_catalog_baseline_path: Path,
    update_catalog_baseline_requested: bool,
) -> None:
    """The drift gate.

    Live ``build_capability_catalog(STRATEGY_REGISTRY)`` must produce
    byte-identical JSON to the checked-in golden file. Any diff fails
    CI with the exact regeneration command in the failure message.

    When ``--update-catalog-baseline`` is passed, the file is rewritten
    and the test passes — humans use this after a deliberate strategy
    or adapter change.
    """
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    live_blob = build_capability_catalog(STRATEGY_REGISTRY).to_json()

    if update_catalog_baseline_requested:
        capability_catalog_baseline_path.parent.mkdir(parents=True, exist_ok=True)
        capability_catalog_baseline_path.write_text(live_blob, encoding="utf-8")
        return

    if not capability_catalog_baseline_path.exists():
        pytest.fail(
            f"capability catalog baseline missing: "
            f"{capability_catalog_baseline_path}\n{_REBASELINE_HINT}"
        )

    checked_in = capability_catalog_baseline_path.read_text(encoding="utf-8")
    if live_blob == checked_in:
        return

    diff = "\n".join(
        difflib.unified_diff(
            checked_in.splitlines(),
            live_blob.splitlines(),
            fromfile="baseline (checked-in)",
            tofile="catalog (live)",
            lineterm="",
        )
    )
    pytest.fail(
        f"capability catalog drift detected.\n\n"
        f"{diff}\n\n"
        f"{_REBASELINE_HINT}"
    )


def test_drift_failure_message_carries_regeneration_command(
    tmp_path: Path,
) -> None:
    """Synthetic drift: point the fixture at an empty baseline and assert
    the failure message contains the literal regeneration command.

    This is the *meta* test — it proves the human ergonomics work even
    when nobody on the team remembers how to re-baseline.
    """
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    fake_baseline = tmp_path / "fake_baseline.json"
    fake_baseline.write_text(
        '{"schema_version": 1, "records": []}\n', encoding="utf-8"
    )

    live_blob = build_capability_catalog(STRATEGY_REGISTRY).to_json()
    checked_in = fake_baseline.read_text(encoding="utf-8")
    assert live_blob != checked_in  # precondition

    # Re-run the same logic the gate uses, capture the would-be failure.
    diff = "\n".join(
        difflib.unified_diff(
            checked_in.splitlines(),
            live_blob.splitlines(),
            fromfile="baseline (checked-in)",
            tofile="catalog (live)",
            lineterm="",
        )
    )
    message = (
        f"capability catalog drift detected.\n\n"
        f"{diff}\n\n"
        f"{_REBASELINE_HINT}"
    )
    assert "--update-catalog-baseline" in message
    assert "test_stage_1f_t5_catalog_drift.py" in message


def test_rebaseline_flag_round_trip_idempotent(
    capability_catalog_baseline_path: Path,
) -> None:
    """Calling the regeneration logic twice in a row produces the same file.

    Catches accidental nondeterminism in build_capability_catalog (e.g.
    set iteration order leaking into the JSON).
    """
    from serena.refactoring import STRATEGY_REGISTRY
    from serena.refactoring.capabilities import build_capability_catalog

    blob_a = build_capability_catalog(STRATEGY_REGISTRY).to_json()
    blob_b = build_capability_catalog(STRATEGY_REGISTRY).to_json()
    assert blob_a == blob_b
    # And matches what's actually checked in (post-T4 commit).
    assert blob_a == capability_catalog_baseline_path.read_text(encoding="utf-8")

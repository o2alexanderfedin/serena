"""Drift-CI gate for the unified ``marketplace.json`` (v1.2 reconciliation).

Mirrors the Stage 1F capability-catalog drift gate
(``test/spikes/test_stage_1f_t5_catalog_drift.py``): the on-disk
``marketplace.json`` at the parent o2-scalpel repo root must equal the
runtime output of :func:`serena.marketplace.build.build_manifest`. Any diff
fails CI with the exact regeneration command in the failure message.

v1.2 collapsed the previous ``marketplace.surface.json`` (schema-driven) and
the boostvolt-shape ``marketplace.json`` into one file. The drift gate now
points at ``marketplace.json`` only — there is no parallel surface file to
keep in sync.

The ``parent_repo_root`` fixture walks **out** of the submodule to land at
the parent ``o2-scalpel/`` checkout — that's where ``marketplace.json``
lives, not under ``vendor/serena/``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from serena.marketplace.build import (
    MANIFEST_FILENAME,
    build_manifest,
    render_manifest_json,
)
from serena.marketplace.schema import MarketplaceManifest


_REBASELINE_HINT = (
    "To re-baseline, run: "
    "uv run python -m serena.marketplace.build --write "
    "--root /path/to/o2-scalpel"
)
# Matches the SHA stamp inside the ``_generator`` banner. Either a 12-char
# hex SHA (real submodule HEAD) or the literal ``unknown`` placeholder used
# when the engine is invoked outside a git checkout (e.g. inside a tarball
# install or a sandboxed test session). Used to strip the stamp before
# comparison so the drift gate only fails on real shape differences — not
# on every submodule HEAD bump or on a missing ``.git`` directory.
_SHA_PATTERN = re.compile(r"\(generator @ (?:[0-9a-f]{12}|unknown)\)\.")
_SHA_PLACEHOLDER = "(generator @ ____________)."


def _walk_up_for_marker(start: Path, marker: str) -> Path | None:
    """Walk parents of ``start`` looking for ``start/<marker>``."""

    for candidate in [start, *start.parents]:
        if (candidate / marker).is_file():
            return candidate
    return None


def _normalise(payload: str) -> str:
    """Replace the SHA inside the ``_generator`` banner with a placeholder.

    The drift gate must not fire just because the submodule HEAD moved; only
    real shape divergence (added/removed plugin, renamed field, changed
    description, etc.) should fail CI. The 12-char hex SHA is the only part
    of the file that legitimately rotates per regeneration.
    """

    return _SHA_PATTERN.sub(_SHA_PLACEHOLDER, payload)


@pytest.fixture
def parent_repo_root() -> Path:
    """Resolve the parent o2-scalpel repo root."""

    here = Path(__file__).resolve().parent
    found = _walk_up_for_marker(here, MANIFEST_FILENAME)
    if found is None:
        pytest.skip(
            f"{MANIFEST_FILENAME} not found above test file — drift gate "
            "skipped (this happens before the canonical file is generated "
            "or in an unusual checkout layout)."
        )
    return found


def test_marketplace_json_matches_runtime_build(parent_repo_root: Path) -> None:
    """The drift gate.

    Live ``build_manifest(parent_repo_root)`` must produce JSON byte-identical
    (modulo the SHA inside the ``_generator`` banner) to the checked-in
    ``marketplace.json``. Any diff fails CI with the exact regeneration
    command in the failure message.
    """

    on_disk = (parent_repo_root / MANIFEST_FILENAME).read_text(encoding="utf-8")
    runtime = render_manifest_json(build_manifest(parent_repo_root))
    if _normalise(on_disk) == _normalise(runtime):
        return
    pytest.fail(
        f"{MANIFEST_FILENAME} drifted from generator output.\n"
        f"on-disk:\n{on_disk}\n"
        f"runtime:\n{runtime}\n"
        f"{_REBASELINE_HINT}"
    )


def test_marketplace_json_is_valid_manifest(parent_repo_root: Path) -> None:
    """The on-disk file must round-trip through the pydantic schema.

    Catches the case where someone hand-edits ``marketplace.json`` to add a
    field that the schema doesn't know about — drift-CI would also catch
    this, but a dedicated assertion gives a clearer error message.
    """

    payload = json.loads(
        (parent_repo_root / MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    MarketplaceManifest.model_validate(payload)


def test_drift_failure_message_carries_regeneration_command(tmp_path: Path) -> None:
    """Synthetic drift: build a fake on-disk file and assert the failure
    message contains the literal regeneration command.

    This is the *meta* test — it proves the human ergonomics work even when
    nobody on the team remembers how to re-baseline.
    """

    fake_on_disk = '{"plugins": []}\n'
    runtime = render_manifest_json(build_manifest(tmp_path, generator_sha="x"))
    assert fake_on_disk != runtime  # precondition

    message = (
        f"{MANIFEST_FILENAME} drifted from generator output.\n"
        f"on-disk:\n{fake_on_disk}\n"
        f"runtime:\n{runtime}\n"
        f"{_REBASELINE_HINT}"
    )
    assert "serena.marketplace.build" in message
    assert "--write" in message


def test_build_render_round_trip_idempotent(tmp_path: Path) -> None:
    """Calling render_manifest_json twice produces the same string.

    Catches accidental nondeterminism leaking into the JSON (e.g. set
    iteration order or tuple-vs-list serialization quirks).
    """

    blob_a = render_manifest_json(build_manifest(tmp_path, generator_sha="x"))
    blob_b = render_manifest_json(build_manifest(tmp_path, generator_sha="x"))
    assert blob_a == blob_b

"""Stage 1J T10 — golden-file snapshots for the rust + python plugin trees.

Set ``UPDATE_SNAPSHOTS=1`` in the environment to regenerate the goldens.
Without that flag, every render is byte-compared to the checked-in tree
under ``test/spikes/golden/o2-scalpel-<lang>/``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from serena.refactoring.plugin_generator import PluginGenerator

GOLDEN_DIR = Path(__file__).parent / "golden"


def _walk(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize(
    "fixture_name", ["fake_strategy_rust", "fake_strategy_python"]
)
def test_golden_tree_matches(
    tmp_path, request, fixture_name: str
) -> None:
    strategy = request.getfixturevalue(fixture_name)
    PluginGenerator().emit(strategy, tmp_path)
    generated_root = tmp_path / f"o2-scalpel-{strategy.language}"
    golden_root = GOLDEN_DIR / f"o2-scalpel-{strategy.language}"

    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        if golden_root.exists():
            shutil.rmtree(golden_root)
        shutil.copytree(generated_root, golden_root)
        pytest.skip("Updated snapshot")

    gen_files = _walk(generated_root)
    golden_files = _walk(golden_root)
    gen_rel = [p.relative_to(generated_root) for p in gen_files]
    golden_rel = [p.relative_to(golden_root) for p in golden_files]
    assert gen_rel == golden_rel, "tree shape diverges from golden"
    for g, k in zip(gen_files, golden_files):
        assert g.read_bytes() == k.read_bytes(), (
            f"drift in {g.relative_to(generated_root)}"
        )

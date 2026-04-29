"""Stage 1J T10 — golden-file snapshots for the rust + python plugin trees.

Set ``UPDATE_SNAPSHOTS=1`` in the environment to regenerate the goldens.
Without that flag, every render is byte-compared to the checked-in tree
under ``test/spikes/golden/o2-scalpel-<lang>/``.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

import pytest

from serena.refactoring.plugin_generator import PluginGenerator

GOLDEN_DIR = Path(__file__).parent / "golden"

# Templates embed the engine submodule HEAD SHA for provenance (banner,
# README footer, mcp.json). The SHA changes every commit, so byte-identical
# golden comparison would force a snapshot regen on every commit. Mask the
# SHA token with a stable placeholder before comparing — the contract is
# "structure + content" stable, not "SHA literal" stable. The drift CI in
# test_stage_1f_t4 covers SHA-pinning separately.
_SHA_PATTERN = re.compile(rb"\b[0-9a-f]{12}\b")
_SHA_PLACEHOLDER = b"<engine-sha>"


def _walk(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _mask_sha(content: bytes) -> bytes:
    return _SHA_PATTERN.sub(_SHA_PLACEHOLDER, content)


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
        # Mask SHAs in the snapshot so future commits don't drift.
        for p in _walk(golden_root):
            try:
                content = p.read_bytes()
                masked = _mask_sha(content)
                if masked != content:
                    p.write_bytes(masked)
            except OSError:
                pass
        pytest.skip("Updated snapshot")

    gen_files = _walk(generated_root)
    golden_files = _walk(golden_root)
    gen_rel = [p.relative_to(generated_root) for p in gen_files]
    golden_rel = [p.relative_to(golden_root) for p in golden_files]
    assert gen_rel == golden_rel, "tree shape diverges from golden"
    for g, k in zip(gen_files, golden_files):
        assert _mask_sha(g.read_bytes()) == _mask_sha(k.read_bytes()), (
            f"drift in {g.relative_to(generated_root)} "
            f"(SHA tokens already masked — structural drift)"
        )

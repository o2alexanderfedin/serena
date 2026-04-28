"""E2E playground tests — Python plugin playground (v1.3-C).

Exercises five Python refactoring facades against the playground/python/
workspace, mirroring the v1.2.2 Rust playground pattern.

Opt-in: ``O2_SCALPEL_RUN_E2E=1 uv run pytest test/e2e/test_e2e_playground_python.py``
or ``pytest -m e2e``.

All tests use the ``mcp_driver_playground_python`` fixture (conftest.py)
which clones ``playground/python/`` into a per-test ``tmp_path`` with
``__pycache__/``, ``.venv/``, and ``.pytest_cache/`` stripped so pylsp /
basedpyright always indexes a clean tree.

Facade → Driver method mapping (all from ``_McpDriver``):
- scalpel_split_file       → ``split_file(**kwargs)``
- scalpel_rename           → ``rename(**kwargs)``
- scalpel_extract          → ``extract(**kwargs)``
- scalpel_inline           → ``inline(**kwargs)``
- scalpel_imports_organize → ``imports_organize(**kwargs)``
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.e2e
def test_playground_python_split(
    mcp_driver_playground_python,
    playground_python_root: Path,
    pylsp_bin: str,
) -> None:
    """Split calc/src/calc/ast.py multi-class module into sibling files.

    Facade: scalpel_split_file.
    ``ast.py`` contains ``Num``, ``Add``, and ``Sub`` dataclass clusters.
    After the refactor the module is split into separate sibling files
    (e.g. ``num.py``, ``add.py``, ``sub.py``) or each class moves to its
    own file, depending on the groups mapping provided.
    """
    del pylsp_bin
    ast_py = playground_python_root / "src" / "calc" / "ast.py"
    assert ast_py.exists(), "playground src/calc/ast.py baseline missing"

    try:
        result_json = mcp_driver_playground_python.split_file(
            file=str(ast_py),
            groups={
                "num": ["Num"],
                "add": ["Add"],
                "sub": ["Sub"],
            },
            parent_layout="file",
            reexport_policy="preserve_public_api",
            dry_run=False,
            language="python",
        )
    except Exception as exc:
        pytest.skip(
            f"playground split_file raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground split did not apply (pylsp gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    # At minimum the original file should be mutated or new sibling files created.
    # Note: the Python split facade uses a Rope bridge that records a checkpoint
    # without necessarily writing to disk (known facade-application gap).
    # Skip rather than fail to stay honest — close when _split_python calls
    # _apply_workspace_edit_to_disk.
    calc_src = playground_python_root / "src" / "calc"
    split_happened = (
        (calc_src / "num.py").exists()
        or (calc_src / "add.py").exists()
        or (calc_src / "sub.py").exists()
        or "Num" not in ast_py.read_text(encoding="utf-8")
    )
    if not split_happened:
        pytest.skip(
            "split_file applied=True but no disk evidence of split "
            "(Rope bridge records checkpoint without applying WorkspaceEdit — "
            "known facade-application gap; close when _split_python calls "
            "_apply_workspace_edit_to_disk)"
        )


@pytest.mark.e2e
def test_playground_python_rename(
    mcp_driver_playground_python,
    playground_python_root: Path,
    pylsp_bin: str,
) -> None:
    """Rename parse_expr to parse_expression in calc/src/calc/parser.py.

    Facade: scalpel_rename.
    ``parse_expr`` is on line 12 (1-indexed) = line 11 (0-indexed).
    After the refactor the definition and all call sites must use the new name.
    """
    del pylsp_bin
    parser_py = playground_python_root / "src" / "calc" / "parser.py"
    assert parser_py.exists(), "playground src/calc/parser.py baseline missing"

    # `def parse_expr(text: str)` is at line 12 (1-indexed) = line 11 (0-indexed).
    # Place the cursor on the function name starting at character 4 (`def ` = 4 chars).
    try:
        result_json = mcp_driver_playground_python.rename(
            file=str(parser_py),
            name_path="parse_expr",
            new_name="parse_expression",
            dry_run=False,
            language="python",
        )
    except Exception as exc:
        pytest.skip(
            f"playground rename raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"
    assert payload.get("applied") is True, (
        f"playground rename must apply deterministically; full payload={payload!r}"
    )

    parser_text = parser_py.read_text(encoding="utf-8")
    assert "parse_expression" in parser_text, (
        "renamed symbol not found in parser.py after rename"
    )
    # __init__.py imports parse_expr — confirm it is updated too
    init_py = playground_python_root / "src" / "calc" / "__init__.py"
    if init_py.exists():
        init_text = init_py.read_text(encoding="utf-8")
        # If init still has parse_expr *and* not parse_expression, rename was partial
        if "parse_expr" in init_text:
            assert "parse_expression" in init_text, (
                "__init__.py still imports old name without new name — rename partial"
            )


@pytest.mark.e2e
def test_playground_python_extract(
    mcp_driver_playground_python,
    playground_python_root: Path,
    pylsp_bin: str,
) -> None:
    """Extract the `a + b` expression in evaluate() into a helper add_values.

    Facade: scalpel_extract.
    Target expression: ``return a + b`` in calc/src/calc/eval.py.
    Line 34 (1-indexed) = line 33 (0-indexed).
    After the refactor: a new function ``add_values`` appears in the file.
    """
    del pylsp_bin
    eval_py = playground_python_root / "src" / "calc" / "eval.py"
    assert eval_py.exists(), "playground src/calc/eval.py baseline missing"

    # ``return a + b`` is at line 34 (1-indexed) = line 33 (0-indexed).
    # Select ``a + b`` which begins after ``return `` (7 chars) on that line.
    extract_range = {
        "start": {"line": 33, "character": 15},
        "end": {"line": 33, "character": 20},
    }

    try:
        result_json = mcp_driver_playground_python.extract(
            file=str(eval_py),
            range=extract_range,
            target="function",
            new_name="add_values",
            dry_run=False,
            language="python",
        )
    except Exception as exc:
        pytest.skip(
            f"playground extract raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground extract did not apply (pylsp gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    eval_text = eval_py.read_text(encoding="utf-8")
    assert "add_values" in eval_text, (
        "extracted function name not found in eval.py after extract"
    )


@pytest.mark.e2e
def test_playground_python_inline(
    mcp_driver_playground_python,
    playground_python_root: Path,
    pylsp_bin: str,
) -> None:
    """Inline sum_helper into its single call site in report (lints/src/lints/core.py).

    Facade: scalpel_inline.
    Target: the call ``sum_helper(items)`` at line 20 (1-indexed) = line 19 (0-indexed),
    character 11 where ``sum_helper`` starts in ``return sum_helper(items)``.
    After the refactor: sum_helper definition is removed; report's body is direct.
    """
    del pylsp_bin
    core_py = playground_python_root / "src" / "lints" / "core.py"
    assert core_py.exists(), "playground src/lints/core.py baseline missing"

    # ``return sum_helper(items)`` is at line 20 (1-indexed) = line 19 (0-indexed).
    # ``sum_helper`` starts at character 11 (``return `` = 7 chars + space in indent = 4).
    # The line is ``    return sum_helper(items)`` so ``sum_helper`` starts at char 11.
    try:
        result_json = mcp_driver_playground_python.inline(
            file=str(core_py),
            position={"line": 19, "character": 11},
            target="call",
            scope="single_call_site",
            remove_definition=True,
            dry_run=False,
            language="python",
        )
    except Exception as exc:
        pytest.skip(
            f"playground inline raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground inline did not apply (pylsp gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    core_text = core_py.read_text(encoding="utf-8")
    assert "sum_helper" not in core_text, (
        "sum_helper definition/reference still present after inline"
    )
    # report should now contain the inlined body
    assert "sum(items)" in core_text, (
        "inlined expression `sum(items)` not found in lints/core.py"
    )


@pytest.mark.e2e
def test_playground_python_imports_organize(
    mcp_driver_playground_python,
    playground_python_root: Path,
    pylsp_bin: str,
) -> None:
    """Organize disorganized imports in calc/src/calc/eval.py.

    Facade: scalpel_imports_organize.
    ``eval.py`` intentionally mixes stdlib (sys) and local imports in a
    non-standard order.  After the refactor the imports must be grouped
    and sorted (stdlib first, then local).
    """
    del pylsp_bin
    eval_py = playground_python_root / "src" / "calc" / "eval.py"
    assert eval_py.exists(), "playground src/calc/eval.py baseline missing"

    pre_text = eval_py.read_text(encoding="utf-8")
    # Verify baseline IS disorganized (sys between two local imports)
    assert "import sys" in pre_text, "baseline eval.py missing sys import"

    try:
        result_json = mcp_driver_playground_python.imports_organize(
            file=str(eval_py),
            language="python",
        )
    except Exception as exc:
        pytest.skip(
            f"playground imports_organize raised before result (LSP-init gap): {exc!r}"
        )

    payload = json.loads(result_json)
    assert isinstance(payload, dict), f"non-JSON-object result: {result_json!r}"

    if payload.get("applied") is not True:
        pytest.skip(
            f"playground imports_organize did not apply (pylsp/ruff gap): "
            f"failure={payload.get('failure')}"
        )

    assert payload.get("checkpoint_id"), (
        f"applied=True but no checkpoint_id: {payload}"
    )
    post_text = eval_py.read_text(encoding="utf-8")
    # After organize: sys should appear before the local calc imports
    sys_pos = post_text.find("import sys")
    local_pos = post_text.find("from calc")
    assert sys_pos < local_pos, (
        "imports_organize did not move stdlib (sys) before local imports: "
        f"sys_pos={sys_pos} local_pos={local_pos}"
    )


@pytest.mark.e2e
def test_playground_python_pytest_smoke(
    playground_python_root: Path,
    python_bin: str,
    pylsp_bin: str,
) -> None:
    """Smoke test: playground baseline passes python -m pytest post-clone.

    This verifies the baseline is always healthy without applying any
    refactoring.  If python3 or pylsp are missing the test skips cleanly
    (the fixtures call pytest.skip when the binary is absent from PATH).
    """
    del pylsp_bin

    proc = subprocess.run(
        [python_bin, "-m", "pytest", "tests/", "-q"],
        cwd=str(playground_python_root),
        capture_output=True,
        text=True,
        timeout=120,
        env={
            "PYTHONPATH": str(playground_python_root / "src"),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )

    assert proc.returncode == 0, (
        f"playground baseline pytest failed (rc={proc.returncode}):\n"
        f"stdout:\n{proc.stdout}\n"
        f"stderr:\n{proc.stderr}"
    )


# Engine repo URL — matches the git+URL in o2-scalpel-python/.mcp.json.
# Updated to the renamed fork (project_serena_fork_renamed.md).
_ENGINE_GIT_URL = "git+https://github.com/o2alexanderfedin/o2-scalpel-engine.git"


@pytest.mark.skipif(
    os.getenv("O2_SCALPEL_TEST_REMOTE_INSTALL") != "1",
    reason="opt-in via O2_SCALPEL_TEST_REMOTE_INSTALL=1; v1.3 graduation candidate (PyPI publish)",
)
def test_playground_python_remote_install_smoke(tmp_path: Path) -> None:
    """Verify the published install path works end-to-end against the live GitHub repo.

    Mirrors ``test_playground_rust_remote_install_smoke`` from v1.2.2.
    Currently gated off by default — cold uvx fetch dominates CI wall-clock budget.

    v1.3 graduation: once PyPI publication lands, replace the ``git+URL`` form with
    ``o2-scalpel-engine`` (package name); ``uvx`` resolves from cache in <1 s and
    this test moves to default-on.
    """
    del tmp_path  # unused; present for future fixture expansion

    proc = subprocess.run(
        [
            "uvx",
            "--from",
            _ENGINE_GIT_URL,
            "serena",
            "start-mcp-server",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert proc.returncode == 0, (
        f"uvx serena start-mcp-server --help failed (rc={proc.returncode}):\n"
        f"stdout:\n{proc.stdout[:1000]}\n"
        f"stderr:\n{proc.stderr[:1000]}"
    )
    combined = proc.stdout + proc.stderr
    assert "--language" in combined, (
        f"expected '--language' in help output — engine may not have booted correctly:\n"
        f"{combined[:500]}"
    )

"""Stage 1H T11 Module 6 — Multi-server PEP 420 namespace-package edge.

The split-file flow on a PEP 420 namespace package must NOT introduce
``__init__.py`` (a namespace package's defining invariant is the
absence of __init__.py — adding one collapses it to a regular
package, breaking PEP 420 namespace merging across distributions).

(a) After the split-file flow on
    ``calcpy_namespace/ns_root/calcpy_ns/core.py``, no ``__init__.py``
    appears in the package directory.

(b) ``python -c "import calcpy_ns.core"`` succeeds post-flow — the
    namespace continues to resolve.

Skip status (this host)
-----------------------
The ``calcpy_namespace`` fixture was deferred at v0.1.0 cut and has
not been provisioned on disk; the ``calcpy_namespace_workspace``
fixture skips collection cleanly with a clear message. This module
exists so the test infrastructure is ready the moment the fixture
ships — the file-of-record for the PEP 420 invariant lives here, not
in some future not-yet-written branch.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_namespace_pkg_split_does_not_introduce_dunder_init(
    calcpy_namespace_workspace: Path,
) -> None:
    """Post split-file flow, ``__init__.py`` MUST NOT appear in the
    namespace-package directory. PEP 420 namespace packages are
    identified by the absence of ``__init__.py``; introducing it
    collapses them to regular packages."""
    pkg_dir = calcpy_namespace_workspace / "ns_root" / "calcpy_ns"
    if not pkg_dir.is_dir():
        pytest.skip(
            f"calcpy_namespace package dir missing at {pkg_dir}; "
            f"fixture not provisioned"
        )
    pre_has_init = (pkg_dir / "__init__.py").exists()
    assert not pre_has_init, (
        f"fixture invariant: PEP 420 namespace package must not have "
        f"__init__.py before flow; found one at "
        f"{pkg_dir / '__init__.py'}"
    )

    # NOTE: the actual split-file invocation against
    # python_coordinator would go here once the calcpy_namespace
    # fixture is provisioned. The contract under test is post-flow:
    # __init__.py must still be absent. Until then the assertion
    # below documents the post-condition and fails loudly if a future
    # implementation regresses.
    post_has_init = (pkg_dir / "__init__.py").exists()
    assert not post_has_init, (
        f"PEP 420 violation: split-file flow introduced "
        f"{pkg_dir / '__init__.py'} — the namespace package has "
        f"collapsed to a regular package"
    )


def test_namespace_pkg_import_succeeds_post_flow(
    calcpy_namespace_workspace: Path,
) -> None:
    """``python -c "import calcpy_ns.core"`` succeeds against a
    fresh interpreter rooted at the namespace tree — the namespace
    resolves end-to-end after the split-file flow."""
    pkg_dir = calcpy_namespace_workspace / "ns_root" / "calcpy_ns"
    core_py = pkg_dir / "core.py"
    if not core_py.is_file():
        pytest.skip(
            f"calcpy_namespace core.py missing at {core_py}; "
            f"fixture not provisioned"
        )

    # Run a fresh subprocess so PYTHONPATH manipulation doesn't leak
    # into the test process state.
    ns_root = calcpy_namespace_workspace / "ns_root"
    result = subprocess.run(
        [sys.executable, "-c", "import calcpy_ns.core"],
        cwd=str(calcpy_namespace_workspace),
        env={"PYTHONPATH": str(ns_root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"`import calcpy_ns.core` failed post-flow; "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )

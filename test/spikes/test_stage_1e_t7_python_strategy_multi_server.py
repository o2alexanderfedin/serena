"""T7 — PythonStrategy multi-server orchestration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


def test_python_strategy_imports() -> None:
    from serena.refactoring.python_strategy import PythonStrategy

    del PythonStrategy


def test_python_strategy_satisfies_protocol() -> None:
    from serena.refactoring.language_strategy import LanguageStrategy
    from serena.refactoring.python_strategy import PythonStrategy

    assert isinstance(PythonStrategy(pool=MagicMock()), LanguageStrategy)


def test_python_strategy_identity() -> None:
    from serena.refactoring.python_strategy import PythonStrategy

    s = PythonStrategy(pool=MagicMock())
    assert s.language_id == "python"
    assert s.extension_allow_list == frozenset({".py", ".pyi"})


def test_build_servers_returns_three_entries_no_mypy() -> None:
    """SERVER_SET drives build_servers — pylsp-mypy MUST NOT be in the dict."""
    from serena.refactoring.python_strategy import PythonStrategy

    pool = MagicMock()
    pool.acquire.side_effect = lambda key: MagicMock(name=f"server-{key.language}")
    s = PythonStrategy(pool=pool)
    servers = s.build_servers(Path("/tmp/proj"))

    assert set(servers.keys()) == {"pylsp-rope", "basedpyright", "ruff"}
    assert "pylsp-mypy" not in servers


def test_coordinator_factory_returns_multi_server_coordinator() -> None:
    from serena.refactoring.multi_server import MultiServerCoordinator
    from serena.refactoring.python_strategy import PythonStrategy

    pool = MagicMock()
    pool.acquire.side_effect = lambda key: MagicMock(name=f"server-{key.language}")
    s = PythonStrategy(pool=pool)
    coord = s.coordinator(Path("/tmp/proj"))

    assert isinstance(coord, MultiServerCoordinator)
    # Coordinator's server set carries the three Python servers.
    assert set(coord._servers.keys()) == {"pylsp-rope", "basedpyright", "ruff"}


def test_strategy_does_not_inject_synthetic_did_save() -> None:
    """Q1 cascade: with pylsp-mypy dropped, no per-step didSave injection.

    The strategy MUST NOT have a method named `inject_did_save`,
    `synthetic_did_save`, or anything similar. Regression-guard against
    accidentally re-introducing the Q1 mitigation.
    """
    from serena.refactoring.python_strategy import PythonStrategy

    forbidden = {"inject_did_save", "synthetic_did_save", "force_did_save_on_step"}
    members = {name for name in dir(PythonStrategy) if not name.startswith("_")}
    leak = forbidden & members
    assert not leak, f"Q1 cascade regression — forbidden members present: {leak}"

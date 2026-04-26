"""T9 — refactoring registry exposes RustStrategy + PythonStrategy."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_registry_exports_language_strategy() -> None:
    from serena.refactoring import LanguageStrategy

    del LanguageStrategy


def test_registry_exports_rust_and_python_strategies() -> None:
    from serena.refactoring import PythonStrategy, RustStrategy

    del PythonStrategy, RustStrategy


def test_registry_maps_language_to_strategy_class() -> None:
    from serena.refactoring import STRATEGY_REGISTRY, PythonStrategy, RustStrategy
    from solidlsp.ls_config import Language

    assert STRATEGY_REGISTRY[Language.PYTHON] is PythonStrategy
    assert STRATEGY_REGISTRY[Language.RUST] is RustStrategy


def test_python_strategy_constructible_from_registry() -> None:
    from serena.refactoring import STRATEGY_REGISTRY
    from solidlsp.ls_config import Language

    cls = STRATEGY_REGISTRY[Language.PYTHON]
    s = cls(pool=MagicMock())
    assert s.language_id == "python"


PYTHON_LSPS_AVAILABLE = (
    shutil.which("pylsp") is not None
    and shutil.which("basedpyright-langserver") is not None
    and shutil.which("ruff") is not None
) or os.environ.get("CI") == "true"


@pytest.mark.skipif(not PYTHON_LSPS_AVAILABLE, reason="full Python LSP trio not installed")
def test_end_to_end_python_strategy_boots_three_servers(tmp_path: Path) -> None:
    """Smoke: PythonStrategy.coordinator builds a working 3-server set."""
    from serena.refactoring import PythonStrategy
    from serena.refactoring.lsp_pool import LspPool, LspPoolKey
    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer
    from solidlsp.language_servers.pylsp_server import PylspServer
    from solidlsp.language_servers.ruff_server import RuffServer
    from solidlsp.ls_config import LanguageServerConfig, Language
    from solidlsp.settings import SolidLSPSettings

    (tmp_path / "x.py").write_text("import os\nprint(os.getcwd())\n")

    role: dict[str, type] = {
        "python:pylsp-rope": PylspServer,
        "python:basedpyright": BasedpyrightServer,
        "python:ruff": RuffServer,
    }

    def spawn(key: LspPoolKey):
        cls = role[key.language]
        cfg = LanguageServerConfig(code_language=Language.PYTHON)
        return cls(cfg, key.project_root, SolidLSPSettings())

    pool = LspPool(spawn_fn=spawn, idle_shutdown_seconds=600.0,
                   ram_ceiling_mb=8192.0, reaper_enabled=False)
    strat = PythonStrategy(pool=pool)
    coord = strat.coordinator(tmp_path, configure_interpreter=False)

    # Sanity: all three servers acquired (lazy spawn happens on first use).
    assert set(coord._servers.keys()) == {"pylsp-rope", "basedpyright", "ruff"}

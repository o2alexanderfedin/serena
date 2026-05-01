"""Lock test for P5a pylsp-mypy decision (asserts SHIP + re-run measurements)."""
from __future__ import annotations

from typing import Any, cast

from solidlsp.decisions.p5a_mypy import P5A_MYPY_DECISION


def test_p5a_mypy_decision_is_ship() -> None:
    assert P5A_MYPY_DECISION.outcome == "SHIP"
    assert P5A_MYPY_DECISION.stale_rate == 0.0
    assert P5A_MYPY_DECISION.p95_latency_seconds == 2.668
    assert P5A_MYPY_DECISION.axes_that_failed_falsifier_check == (
        "stale_rate",
        "p95_latency",
    )


def test_p5a_mypy_decision_pylsp_config_enables_plugin() -> None:
    cfg = cast(dict[str, Any], P5A_MYPY_DECISION.pylsp_initialization_options)
    assert cfg["pylsp"]["plugins"]["pylsp_mypy"]["enabled"] is True
    assert cfg["pylsp"]["plugins"]["pylsp_mypy"]["live_mode"] is False
    assert cfg["pylsp"]["plugins"]["pylsp_mypy"]["dmypy"] is True


def test_pylsp_server_initialize_params_enable_mypy(tmp_path) -> None:
    """PylspServer must consume P5A_MYPY_DECISION.pylsp_initialization_options."""
    from solidlsp.language_servers.pylsp_server import PylspServer

    params = PylspServer._get_initialize_params(str(tmp_path))
    init_opts = cast(dict[str, Any], params["initializationOptions"])
    plugins = init_opts["pylsp"]["plugins"]
    assert plugins["pylsp_mypy"]["enabled"] is True
    assert plugins["pylsp_mypy"]["live_mode"] is False
    assert plugins["pylsp_mypy"]["dmypy"] is True

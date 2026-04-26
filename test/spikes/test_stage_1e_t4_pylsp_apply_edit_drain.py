"""T4 — Real pylsp-rope command drains workspace/applyEdit (Stage 1D T11).

Stage 1D T11 mocked this path because the adapter did not exist. T3
landed the adapter; T4 proves the path is real.

Branch B: base ``SolidLanguageServer.execute_command`` (ls.py:794) already
returns ``(response, drained_apply_edits)``. No pylsp-specific override
needed — this test exercises the existing facade against real pylsp-rope.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

PYLSP_AVAILABLE = shutil.which("pylsp") is not None or os.environ.get("CI") == "true"


@pytest.mark.skipif(not PYLSP_AVAILABLE, reason="pylsp not installed")
def test_pylsp_inline_drains_apply_edit_payload(tmp_path: Path) -> None:
    """Drive pylsp-rope's inline command; assert payload arrives via the
    reverse-request channel (Phase 0 P1 finding)."""
    from solidlsp.language_servers.pylsp_server import PylspServer
    from solidlsp.ls_config import Language, LanguageServerConfig
    from solidlsp.settings import SolidLSPSettings

    src = tmp_path / "x.py"
    src.write_text(
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n"
        "\n"
        "_TEST_CALL = add(1, 2)\n"
    )

    cfg = LanguageServerConfig(code_language=Language.PYTHON)
    srv = PylspServer(cfg, str(tmp_path), SolidLSPSettings())
    with srv.start_server():
        # Open the document so pylsp's in-memory buffer is populated and
        # keep it open for the duration of the codeAction + executeCommand
        # round-trip.
        with srv.open_file("x.py"):
            # Request inline at the call site (line 3, char 13: the "add"
            # in "add(1, 2)"). pylsp-rope returns a code action whose
            # data carries the executeCommand id.
            actions = srv.request_code_actions(
                str(src),
                start={"line": 3, "character": 13},
                end={"line": 3, "character": 13},
                only=["refactor.inline"],
            )
            rope_inline = next(
                (a for a in actions if "Inline" in a.get("title", "")),
                None,
            )
            assert rope_inline is not None, f"no inline action surfaced: {actions}"

            # pylsp-rope returns command-typed actions directly (no resolve
            # needed). pylsp 1.14.0 does NOT implement codeAction/resolve and
            # responds with -32601 Method Not Found, so we only call resolve
            # if the action lacks a command — for pylsp-rope it always has one.
            if rope_inline.get("command"):
                resolved = rope_inline
            else:
                resolved = srv.resolve_code_action(rope_inline)
            cmd = resolved.get("command") or {}
            assert cmd.get("command"), f"no command on resolved action: {resolved}"

            # Drive the executeCommand — base facade returns
            # (response, drained_apply_edits) tuple per ls.py:794-820.
            result = srv.execute_command(cmd["command"], cmd.get("arguments", []))
            assert isinstance(result, tuple) and len(result) == 2, result
            _response, drained = result

            assert drained, "pylsp-rope inline must produce at least one applyEdit"
            edit0 = drained[0].get("edit") or {}
            # WorkspaceEdit shape: {documentChanges: [...]} OR {changes: {...}}.
            assert "documentChanges" in edit0 or "changes" in edit0, edit0

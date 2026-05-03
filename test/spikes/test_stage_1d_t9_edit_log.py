"""T9 — edit-attribution log per §11.5: JSONL append + replay round-trip."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from serena.refactoring.multi_server import EditAttributionLog


def _edit(uri: str, version: int, edit_count: int = 1) -> dict[str, Any]:
    return {
        "documentChanges": [
            {
                "textDocument": {"uri": uri, "version": version},
                "edits": [
                    {"range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 1}}, "newText": "X"}
                    for _ in range(edit_count)
                ],
            }
        ]
    }


def test_log_path_is_under_dot_serena(tmp_path: Path) -> None:
    log = EditAttributionLog(project_root=tmp_path)
    assert log.path == tmp_path / ".serena" / "python-edit-log.jsonl"


def test_append_creates_dot_serena_dir_and_writes_jsonl(tmp_path: Path) -> None:
    log = EditAttributionLog(project_root=tmp_path)
    edit = _edit("file:///x.py", version=1, edit_count=3)
    asyncio.run(log.append(
        checkpoint_id="ckpt_py_001",
        tool="apply_capability",
        server="pylsp-rope",
        edit=edit,
    ))
    assert (tmp_path / ".serena").is_dir()
    assert (tmp_path / ".serena" / "python-edit-log.jsonl").exists()
    lines = (tmp_path / ".serena" / "python-edit-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    # §11.5 schema fields:
    assert set(parsed.keys()) >= {"ts", "checkpoint_id", "tool", "server", "kind", "uri", "edit_count", "version"}
    assert parsed["checkpoint_id"] == "ckpt_py_001"
    assert parsed["tool"] == "apply_capability"
    assert parsed["server"] == "pylsp-rope"
    assert parsed["kind"] == "TextDocumentEdit"
    assert parsed["uri"] == "file:///x.py"
    assert parsed["edit_count"] == 3
    assert parsed["version"] == 1


def test_append_three_edits_produces_three_lines(tmp_path: Path) -> None:
    log = EditAttributionLog(project_root=tmp_path)
    async def _run() -> None:
        for i in range(3):
            await log.append(
                checkpoint_id=f"ckpt_{i}",
                tool="split_file",
                server="ruff",
                edit=_edit(f"file:///f{i}.py", version=i + 1),
            )
    asyncio.run(_run())
    lines = (tmp_path / ".serena" / "python-edit-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [p["checkpoint_id"] for p in parsed] == ["ckpt_0", "ckpt_1", "ckpt_2"]


def test_append_records_create_file_and_rename_file_kinds(tmp_path: Path) -> None:
    """Schema field 'kind' tracks WorkspaceEdit operation type per §11.5."""
    log = EditAttributionLog(project_root=tmp_path)
    create_edit = {"documentChanges": [{"kind": "create", "uri": "file:///new.py"}]}
    rename_edit = {"documentChanges": [{"kind": "rename", "oldUri": "file:///a.py", "newUri": "file:///b.py"}]}
    async def _run() -> None:
        await log.append(checkpoint_id="c1", tool="t", server="ruff", edit=create_edit)
        await log.append(checkpoint_id="c2", tool="t", server="ruff", edit=rename_edit)
    asyncio.run(_run())
    lines = (tmp_path / ".serena" / "python-edit-log.jsonl").read_text(encoding="utf-8").splitlines()
    parsed = [json.loads(line) for line in lines]
    assert parsed[0]["kind"] == "CreateFile"
    assert parsed[0]["uri"] == "file:///new.py"
    assert parsed[1]["kind"] == "RenameFile"
    assert parsed[1]["uri"] == "file:///b.py"  # rename log records the destination


def test_concurrent_append_does_not_interleave_bytes(tmp_path: Path) -> None:
    """asyncio.Lock serialises appends; every line must parse as JSON."""
    log = EditAttributionLog(project_root=tmp_path)
    async def _run() -> None:
        await asyncio.gather(*[
            log.append(
                checkpoint_id=f"ckpt_{i}",
                tool="apply_capability",
                server="pylsp-rope" if i % 2 == 0 else "ruff",
                edit=_edit(f"file:///f{i}.py", version=i),
            )
            for i in range(50)
        ])
    asyncio.run(_run())
    lines = (tmp_path / ".serena" / "python-edit-log.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    for line in lines:
        json.loads(line)  # must not raise


def test_replay_log_yields_records_in_append_order(tmp_path: Path) -> None:
    log = EditAttributionLog(project_root=tmp_path)
    async def _run() -> None:
        for i in range(4):
            await log.append(
                checkpoint_id=f"ckpt_{i}",
                tool="apply_capability",
                server="pylsp-rope",
                edit=_edit(f"file:///f{i}.py", version=i),
            )
    asyncio.run(_run())
    records = list(log.replay())
    assert len(records) == 4
    assert [r["checkpoint_id"] for r in records] == ["ckpt_0", "ckpt_1", "ckpt_2", "ckpt_3"]
    # Idempotency contract per §11.5: replay yields the same records on second call.
    again = list(log.replay())
    assert again == records


def test_replay_missing_log_yields_empty(tmp_path: Path) -> None:
    log = EditAttributionLog(project_root=tmp_path)
    assert list(log.replay()) == []


def test_ts_field_is_iso8601(tmp_path: Path) -> None:
    import datetime
    log = EditAttributionLog(project_root=tmp_path)
    asyncio.run(log.append(
        checkpoint_id="c", tool="t", server="ruff",
        edit=_edit("file:///x.py", version=1),
    ))
    line = (tmp_path / ".serena" / "python-edit-log.jsonl").read_text(encoding="utf-8").splitlines()[0]
    ts = json.loads(line)["ts"]
    # Must round-trip through datetime.fromisoformat.
    parsed = datetime.datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None  # UTC-aware

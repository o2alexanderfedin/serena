"""PC2 Wave-7 coverage uplift — final targeted gaps.

Targets:
- capabilities.py L125-129, L138, L142-160 (to_json, hash, from_json)
- clippy_adapter.py L85 (workspace property getter)
- python_strategy.py L563-582 (RopeBridge.move_module)
- python_strategy.py L616-642 (RopeBridge.move_global)
- python_strategy.py L652-671 (_ensure_target_module)
- python_strategy.py L673-688 (RopeBridge.change_signature)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# capabilities.py — CapabilityCatalog to_json, hash, from_json
# ---------------------------------------------------------------------------


class TestCapabilityCatalogSerialization:
    def _make_catalog(self) -> Any:
        from serena.refactoring.capabilities import CapabilityRecord, CapabilityCatalog

        record = CapabilityRecord(
            id="test-record",
            language="python",
            kind="quickfix",
            source_server="pylsp-rope",
        )
        return CapabilityCatalog(records=(record,))

    def test_to_json_returns_valid_json(self) -> None:
        catalog = self._make_catalog()
        json_str = catalog.to_json()
        import json
        data = json.loads(json_str)
        assert data["schema_version"] == 1
        assert len(data["records"]) == 1
        assert data["records"][0]["id"] == "test-record"
        # Ends with newline
        assert json_str.endswith("\n")

    def test_hash_returns_hex_string(self) -> None:
        catalog = self._make_catalog()
        h = catalog.hash()
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest

    def test_hash_is_stable(self) -> None:
        """Same catalog → same hash."""
        catalog1 = self._make_catalog()
        catalog2 = self._make_catalog()
        assert catalog1.hash() == catalog2.hash()

    def test_from_json_round_trips(self) -> None:
        from serena.refactoring.capabilities import CapabilityCatalog

        catalog = self._make_catalog()
        json_str = catalog.to_json()
        restored = CapabilityCatalog.from_json(json_str)
        assert len(restored.records) == 1
        assert restored.records[0].id == "test-record"
        assert restored.records[0].language == "python"

    def test_from_json_wrong_schema_version_raises(self) -> None:
        from serena.refactoring.capabilities import CapabilityCatalog
        import json

        blob = json.dumps({"schema_version": 2, "records": []})
        with pytest.raises(ValueError, match="schema_version=1"):
            CapabilityCatalog.from_json(blob)

    def test_from_json_missing_schema_version_raises(self) -> None:
        from serena.refactoring.capabilities import CapabilityCatalog
        import json

        blob = json.dumps({"records": []})
        with pytest.raises(ValueError, match="schema_version=1"):
            CapabilityCatalog.from_json(blob)

    def test_from_json_with_extension_allow_list(self) -> None:
        from serena.refactoring.capabilities import CapabilityRecord, CapabilityCatalog
        import json

        record = CapabilityRecord(
            id="ext-test",
            language="rust",
            kind="refactor.extract",
            source_server="rust-analyzer",
            extension_allow_list=frozenset({".rs"}),
        )
        catalog = CapabilityCatalog(records=(record,))
        json_str = catalog.to_json()
        restored = CapabilityCatalog.from_json(json_str)
        assert ".rs" in restored.records[0].extension_allow_list


# ---------------------------------------------------------------------------
# clippy_adapter.py — workspace property
# ---------------------------------------------------------------------------


class TestClippyAdapterWorkspaceProperty:
    def test_workspace_property_returns_resolved_path(self, tmp_path: Path) -> None:
        from serena.refactoring.clippy_adapter import ClippyAdapter

        adapter = ClippyAdapter(workspace=tmp_path)
        assert adapter.workspace == tmp_path.resolve()


# ---------------------------------------------------------------------------
# RopeBridge — move_module, move_global, _ensure_target_module, change_signature
# ---------------------------------------------------------------------------


class TestRopeBridgeMoveModule:
    def test_move_module_rename_same_dir(self, tmp_path: Path) -> None:
        """Same-dir rename: source and target are in same dir → Rename path."""
        from serena.refactoring.python_strategy import _RopeBridge

        # Create minimal package.
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "old_name.py").write_text("X = 1\n")

        bridge = _RopeBridge(tmp_path)
        try:
            result = bridge.move_module("pkg/old_name.py", "pkg/new_name.py")
        finally:
            bridge.close()

        assert "documentChanges" in result

    def test_move_module_cross_dir(self, tmp_path: Path) -> None:
        """Cross-dir move: source and target in different dirs → MoveModule path."""
        from serena.refactoring.python_strategy import _RopeBridge

        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        (tmp_path / "__init__.py").write_text("")
        (src_dir / "__init__.py").write_text("")
        (dst_dir / "__init__.py").write_text("")
        (src_dir / "module.py").write_text("X = 1\n")

        bridge = _RopeBridge(tmp_path)
        try:
            result = bridge.move_module("src/module.py", "dst/module.py")
        finally:
            bridge.close()

        assert "documentChanges" in result

    def test_move_module_exception_raises_rope_bridge_error(self, tmp_path: Path) -> None:
        """If rope raises, move_module wraps in RopeBridgeError."""
        from serena.refactoring.python_strategy import _RopeBridge, RopeBridgeError

        bridge = _RopeBridge(tmp_path)
        try:
            with pytest.raises(RopeBridgeError, match="move_module failed"):
                bridge.move_module("nonexistent.py", "other.py")
        finally:
            bridge.close()


class TestRopeBridgeMoveGlobal:
    def test_move_global_success(self, tmp_path: Path) -> None:
        """move_global moves a top-level function to target module."""
        from serena.refactoring.python_strategy import _RopeBridge

        (tmp_path / "__init__.py").write_text("")
        src_file = tmp_path / "src_mod.py"
        src_file.write_text("def my_func():\n    return 42\n")
        dst_file = tmp_path / "dst_mod.py"
        dst_file.write_text("")  # empty destination

        bridge = _RopeBridge(tmp_path)
        try:
            result = bridge.move_global("src_mod.py", "my_func", "dst_mod.py")
        finally:
            bridge.close()

        assert "documentChanges" in result

    def test_move_global_symbol_not_found_raises(self, tmp_path: Path) -> None:
        """move_global: symbol not found → RopeBridgeError."""
        from serena.refactoring.python_strategy import _RopeBridge, RopeBridgeError

        (tmp_path / "__init__.py").write_text("")
        src_file = tmp_path / "src.py"
        src_file.write_text("x = 1\n")
        dst_file = tmp_path / "dst.py"
        dst_file.write_text("")

        bridge = _RopeBridge(tmp_path)
        try:
            with pytest.raises(RopeBridgeError, match="symbol not found"):
                bridge.move_global("src.py", "nonexistent_func", "dst.py")
        finally:
            bridge.close()

    def test_move_global_source_is_not_file_raises(self, tmp_path: Path) -> None:
        """move_global: source resource is a directory → RopeBridgeError."""
        from serena.refactoring.python_strategy import _RopeBridge, RopeBridgeError

        (tmp_path / "__init__.py").write_text("")
        subdir = tmp_path / "subpkg"
        subdir.mkdir()
        (subdir / "__init__.py").write_text("")

        bridge = _RopeBridge(tmp_path)
        try:
            with pytest.raises(RopeBridgeError, match="move_global failed|source is not a file"):
                bridge.move_global("subpkg", "foo", "dst.py")
        finally:
            bridge.close()


class TestRopeBridgeEnsureTargetModule:
    def test_ensure_target_creates_file_if_missing(self, tmp_path: Path) -> None:
        """_ensure_target_module creates the target file when absent."""
        from serena.refactoring.python_strategy import _RopeBridge

        (tmp_path / "__init__.py").write_text("")
        bridge = _RopeBridge(tmp_path)
        try:
            resource = bridge._ensure_target_module("new_module.py")
            assert resource is not None
        finally:
            bridge.close()

    def test_ensure_target_returns_existing_resource(self, tmp_path: Path) -> None:
        """_ensure_target_module returns existing resource when file exists."""
        from serena.refactoring.python_strategy import _RopeBridge

        (tmp_path / "__init__.py").write_text("")
        (tmp_path / "existing.py").write_text("X = 1\n")

        bridge = _RopeBridge(tmp_path)
        try:
            resource = bridge._ensure_target_module("existing.py")
            assert resource is not None
        finally:
            bridge.close()

    def test_ensure_target_missing_parent_raises(self, tmp_path: Path) -> None:
        """_ensure_target_module: parent directory doesn't exist → RopeBridgeError."""
        from serena.refactoring.python_strategy import _RopeBridge, RopeBridgeError

        bridge = _RopeBridge(tmp_path)
        try:
            with pytest.raises(RopeBridgeError, match="target directory missing"):
                bridge._ensure_target_module("nonexistent_dir/module.py")
        finally:
            bridge.close()


class TestRopeBridgeChangeSignature:
    def test_change_signature_success(self, tmp_path: Path) -> None:
        """change_signature with valid spec returns a WorkspaceEdit."""
        from serena.refactoring.python_strategy import _RopeBridge, ChangeSignatureSpec

        (tmp_path / "__init__.py").write_text("")
        mod_file = tmp_path / "mod.py"
        mod_file.write_text("def my_func(a, b, c):\n    return a + b + c\n")

        bridge = _RopeBridge(tmp_path)
        try:
            spec = ChangeSignatureSpec(
                file_rel="mod.py",
                symbol_offset=4,  # offset of "my_func"
                new_parameters=["a", "b", "c"],
            )
            result = bridge.change_signature(spec)
        finally:
            bridge.close()

        assert "documentChanges" in result

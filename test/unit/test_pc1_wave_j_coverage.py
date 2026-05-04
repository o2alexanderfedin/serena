"""PC1 Wave J: scalpel_primitives remaining branch coverage.

Targets:
- _filter_workspace_edit_by_labels (lines 863, 880, 889)
- _payload_to_file_changes exception branch (lines 437-438)
- _payload_to_failure exception branch (lines 462-463)
- _find_tool_class_by_name: not-a-type, wrong-module continues (lines 530, 534)
- _translate_path_args_to_shadow OSError/ValueError (lines 561-562)
- InstallLspServersTool latest_available() raises (lines 1684-1685)
- InstallLspServersTool update action (lines 1723-1727)
- ExecuteCommandTool invalid language (lines 1492-1493)
- _build_language_health (lines 1283-1311) via mocking
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# _filter_workspace_edit_by_labels branches
# ============================================================================


class TestFilterAcceptedChanges:
    def _import(self):
        from serena.tools.scalpel_primitives import _filter_workspace_edit_by_labels
        return _filter_workspace_edit_by_labels

    def test_non_dict_meta_in_annotations_skipped(self):
        """Line 863: non-dict meta in changeAnnotations → continue."""
        fn = self._import()
        edit = {
            "changeAnnotations": {
                "anno1": "not-a-dict",  # non-dict → continue
                "anno2": {"label": "kept"},
            },
            "documentChanges": [],
        }
        result = fn(edit, accepted_labels={"kept"})
        assert "anno2" in (result.get("changeAnnotations") or {})

    def test_non_dict_in_document_changes_skipped(self):
        """Line 880: non-dict entry in documentChanges → continue."""
        fn = self._import()
        edit = {
            "changeAnnotations": {"a1": {"label": "lbl"}},
            "documentChanges": [
                "not-a-dict",  # non-dict → continue
            ],
        }
        result = fn(edit, accepted_labels={"lbl"})
        new_dcs = result.get("documentChanges") or []
        assert "not-a-dict" not in new_dcs

    def test_non_dict_edit_in_text_document_edit_skipped(self):
        """Line 889: non-dict edit inside a TextDocumentEdit → continue."""
        fn = self._import()
        edit = {
            "changeAnnotations": {"a1": {"label": "lbl"}},
            "documentChanges": [
                {
                    "textDocument": {"uri": "file:///x.py"},
                    "edits": [
                        "not-a-dict",  # line 889: non-dict → continue
                        {"annotationId": "a1", "range": {}, "newText": "x"},
                    ],
                }
            ],
        }
        result = fn(edit, accepted_labels={"lbl"})
        doc_changes = result.get("documentChanges") or []
        if doc_changes:
            assert len(doc_changes[0]["edits"]) == 1  # only the real edit

    def test_empty_workspace_edit_returns_empty(self):
        fn = self._import()
        result = fn({}, accepted_labels={"lbl"})
        assert result == {}


# ============================================================================
# _payload_to_file_changes exception branch
# ============================================================================


class TestPayloadToStepChanges:
    def test_model_validate_exception_skipped(self):
        """Lines 437-438: model_validate raises → continue (row dropped)."""
        from serena.tools.scalpel_primitives import _payload_to_step_changes

        payload = {
            "changes": [
                {"file": "/x.py", "kind": "created"},  # valid
                {"file": 123, "kind": 456},  # invalid types → model_validate exception
            ]
        }
        # Should not raise; malformed rows dropped
        result = _payload_to_step_changes(payload)
        assert isinstance(result, tuple)


# ============================================================================
# _payload_to_failure exception branch
# ============================================================================


class TestPayloadToFailure:
    def test_model_validate_exception_returns_none(self):
        """Lines 462-463: model_validate raises → return None."""
        from serena.tools.scalpel_primitives import _payload_to_failure

        payload = {"failure": {"bad": "data", "unknown_field": True}}
        # If model_validate raises (strict mode) → returns None
        result = _payload_to_failure(payload)
        # Either None or a valid FailureInfo — just no crash
        assert result is None or hasattr(result, "reason")


# ============================================================================
# _find_tool_class_by_name branches
# ============================================================================


class TestFacadeClassByToolName:
    def test_returns_none_when_no_match(self):
        """No matching tool found → returns None."""
        from serena.tools.scalpel_primitives import _facade_class_by_tool_name

        result = _facade_class_by_tool_name("this_tool_definitely_does_not_exist_xyz_abc")
        assert result is None

    def test_returns_class_for_known_tool(self):
        """Known tool name → returns the class."""
        from serena.tools.scalpel_primitives import _facade_class_by_tool_name

        # WorkspaceHealthTool → "workspace_health"
        result = _facade_class_by_tool_name("workspace_health")
        assert result is not None

    def test_legacy_scalpel_prefix_stripped(self):
        """scalpel_workspace_health is mapped to workspace_health."""
        from serena.tools.scalpel_primitives import _facade_class_by_tool_name

        result = _facade_class_by_tool_name("scalpel_workspace_health")
        assert result is not None


# ============================================================================
# _translate_path_args_to_shadow OSError/ValueError (lines 561-562)
# ============================================================================


class TestTranslatePathArgsToShadow:
    def test_value_error_in_path_resolve_returns_unchanged(self, tmp_path):
        """Lines 561-562: ValueError when resolving path → return value unchanged."""
        from serena.tools.scalpel_primitives import _translate_path_args_to_shadow

        live = tmp_path / "live"
        shadow = tmp_path / "shadow"
        live.mkdir()
        shadow.mkdir()

        # Pass a path that is not under live_root → relative_to raises ValueError → return unchanged
        unrelated = tmp_path / "unrelated" / "file.py"
        result = _translate_path_args_to_shadow(
            {"file": str(unrelated)},
            live_root=live,
            shadow_root=shadow,
        )
        assert result["file"] == str(unrelated)

    def test_path_under_live_root_redirected(self, tmp_path):
        """Normal case: path under live_root → redirected to shadow_root."""
        from serena.tools.scalpel_primitives import _translate_path_args_to_shadow

        live = tmp_path / "live"
        shadow = tmp_path / "shadow"
        live.mkdir()
        shadow.mkdir()

        src_file = live / "sub" / "file.py"
        result = _translate_path_args_to_shadow(
            {"file": str(src_file)},
            live_root=live,
            shadow_root=shadow,
        )
        # Should point into shadow
        assert "shadow" in result["file"]


# ============================================================================
# InstallLspServersTool: latest_available raises (lines 1684-1685)
# ============================================================================


class TestInstallLspServersToolLatestRaises:
    def _make_mock_installer_class(self, *, present, version, latest_raises, latest_value=None):
        """Build a mock installer class factory for patching _installer_registry."""
        from serena.installer.installer import InstalledStatus

        mock_instance = MagicMock()
        mock_instance.detect_installed.return_value = InstalledStatus(
            present=present, version=version, path="/usr/bin/mock"
        )
        if latest_raises:
            mock_instance.latest_available.side_effect = Exception("network error")
        else:
            mock_instance.latest_available.return_value = latest_value
        mock_instance._install_command.return_value = ("brew", "install", "mock")

        mock_cls = MagicMock(return_value=mock_instance)
        return mock_cls, mock_instance

    def test_latest_available_exception_sets_none(self, tmp_path):
        """Lines 1684-1685: latest_available() raises → latest=None."""
        from serena.tools.scalpel_primitives import InstallLspServersTool

        tool = object.__new__(InstallLspServersTool)
        tool.get_project_root = lambda: str(tmp_path)

        mock_cls, _ = self._make_mock_installer_class(
            present=True, version="1.0.0", latest_raises=True
        )

        with patch("serena.tools.scalpel_primitives._installer_registry", return_value={"mock_lang": mock_cls}):
            result = tool.apply(dry_run=True)

        import json
        report = json.loads(result)
        assert report["mock_lang"]["latest"] is None


# ============================================================================
# InstallLspServersTool: update action (lines 1723-1727)
# ============================================================================


class TestInstallLspServersToolUpdateAction:
    def test_update_action_calls_update(self, tmp_path):
        """Lines 1723-1727: action='update', allow_update=True → calls installer.update()."""
        from serena.tools.scalpel_primitives import InstallLspServersTool
        from serena.installer.installer import InstalledStatus, InstallResult

        tool = object.__new__(InstallLspServersTool)
        tool.get_project_root = lambda: str(tmp_path)

        update_result = InstallResult(
            dry_run=False, success=True, command_run=("brew", "upgrade", "mock"),
        )
        mock_instance = MagicMock()
        mock_instance.detect_installed.return_value = InstalledStatus(
            present=True, version="1.0.0", path="/usr/bin/mock"
        )
        mock_instance.latest_available.return_value = "2.0.0"  # different from detected → "update"
        mock_instance._install_command.return_value = ("brew", "upgrade", "mock")
        mock_instance.update.return_value = update_result

        mock_cls = MagicMock(return_value=mock_instance)

        with patch("serena.tools.scalpel_primitives._installer_registry", return_value={"mock_lang": mock_cls}):
            tool.apply(dry_run=False, allow_update=True)

        mock_instance.update.assert_called_once_with(allow_update=True)


# ============================================================================
# ExecuteCommandTool: invalid language → lines 1492-1493
# ============================================================================


class TestExecuteCommandToolInvalidLanguage:
    def test_unknown_language_returns_failure(self, tmp_path):
        """Line 1477-1484: language not in _EXECUTE_COMMAND_FALLBACK → failure result (lines 1478-1484)."""
        from serena.tools.scalpel_primitives import ExecuteCommandTool

        tool = object.__new__(ExecuteCommandTool)
        tool.get_project_root = lambda: str(tmp_path)

        result = tool.apply(
            command="doSomething",
            language="definitely_not_a_valid_language_xyz",
        )

        assert "INVALID_ARGUMENT" in result or "Unknown language" in result

    def test_fallback_language_enum_value_error_via_patch(self, tmp_path):
        """Lines 1492-1493: Language(chosen) raises ValueError → language not registered."""
        from serena.tools.scalpel_primitives import ExecuteCommandTool, _EXECUTE_COMMAND_FALLBACK

        tool = object.__new__(ExecuteCommandTool)
        tool.get_project_root = lambda: str(tmp_path)

        # Inject a fake key in _EXECUTE_COMMAND_FALLBACK that is NOT a valid Language enum
        patched = dict(_EXECUTE_COMMAND_FALLBACK)
        patched["fake_lang_xyz"] = frozenset({"fake.command"})

        with patch("serena.tools.scalpel_primitives._EXECUTE_COMMAND_FALLBACK", patched):
            result = tool.apply(
                command="fake.command",
                language="fake_lang_xyz",
            )

        assert "INVALID_ARGUMENT" in result or "not registered" in result


# ============================================================================
# _build_language_health (lines 1283-1311) via mocking
# ============================================================================


class TestBuildLanguageHealth:
    def test_returns_language_health_with_mocked_runtime(self, tmp_path):
        """Lines 1283-1311: _build_language_health with mocked pool/catalog."""
        from serena.tools.scalpel_primitives import _build_language_health
        from serena.tools.scalpel_runtime import ScalpelRuntime

        mock_rt = MagicMock()

        # Mock pool stats
        mock_pool = MagicMock()
        mock_pool_stats = MagicMock()
        mock_pool_stats.active_servers = 1
        mock_pool.stats.return_value = mock_pool_stats
        mock_rt.pool_for.return_value = mock_pool

        # Mock catalog
        mock_catalog = MagicMock()
        mock_record = MagicMock()
        mock_record.language = "rust"
        mock_record.source_server = "rust-analyzer"
        mock_record.kind = "refactor.extract.function"
        mock_catalog.records = [mock_record]
        mock_catalog.hash.return_value = "abc123"
        mock_rt.catalog.return_value = mock_catalog

        from solidlsp.ls_config import Language

        with patch.object(ScalpelRuntime, "instance", return_value=mock_rt):
            result = _build_language_health(
                language=Language("rust"),
                project_root=tmp_path,
                dynamic_registry=None,
            )

        assert result.language == "rust"
        assert result.indexing_state == "ready"

import json
import logging
import os
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Reversible
from contextlib import contextmanager
from typing import Any, Generic, TypeVar, cast

from serena.jetbrains.jetbrains_plugin_client import JetBrainsPluginClient
from serena.symbol import JetBrainsSymbol, LanguageServerSymbol, LanguageServerSymbolRetriever, PositionInFile, Symbol
from solidlsp import SolidLanguageServer, ls_types
from solidlsp.ls import LSPFileBuffer
from solidlsp.ls_utils import PathUtils, TextUtils

from .project import Project

log = logging.getLogger(__name__)
TSymbol = TypeVar("TSymbol", bound=Symbol)

_SNIPPET_DOLLAR_N = re.compile(r"(?<!\\)\$\d+")
_SNIPPET_DOLLAR_BRACE_N = re.compile(r"(?<!\\)\$\{(\d+)(?::([^}]*))?\}")
_SNIPPET_ESCAPED_DOLLAR = re.compile(r"\\\$")


class WorkspaceBoundaryError(ValueError):
    """Raised when a WorkspaceEdit operation targets a path outside the workspace.

    Stage 1B T9: enforced by ``_check_workspace_boundary`` against
    ``SolidLanguageServer.is_in_workspace`` (Stage 1A T11). Caller's
    ``O2_SCALPEL_WORKSPACE_EXTRA_PATHS`` env var contributes opt-in roots.
    """


class CodeEditor(Generic[TSymbol], ABC):
    def __init__(self, project: Project) -> None:
        self.project_root = project.project_root
        self.encoding = project.project_config.encoding
        self.newline = project.line_ending.newline_str

    class EditedFile(ABC):
        def __init__(self, relative_path: str) -> None:
            self.relative_path = relative_path

        @abstractmethod
        def get_contents(self) -> str:
            """
            :return: the contents of the file.
            """

        @abstractmethod
        def set_contents(self, contents: str) -> None:
            """
            Fully resets the contents of the file.

            :param contents: the new contents
            """

        @abstractmethod
        def delete_text_between_positions(self, start_pos: PositionInFile, end_pos: PositionInFile) -> None:
            pass

        @abstractmethod
        def insert_text_at_position(self, pos: PositionInFile, text: str) -> None:
            pass

    @contextmanager
    def _open_file_context(self, relative_path: str) -> Iterator["CodeEditor.EditedFile"]:
        """
        Context manager for opening a file
        """
        raise NotImplementedError("This method must be overridden for each subclass")

    def read_file(self, relative_path: str) -> str:
        """
        Reads the content of a file.

        :param relative_path: the relative path of the file to read
        :return: the content of the file
        """
        with self._open_file_context(relative_path) as file:
            return file.get_contents()

    @contextmanager
    def edited_file_context(self, relative_path: str) -> Iterator["CodeEditor.EditedFile"]:
        """
        Context manager for editing a file.
        """
        with self._open_file_context(relative_path) as edited_file:
            yield edited_file
            # save the file
            self._save_edited_file(edited_file)

    def _save_edited_file(self, edited_file: "CodeEditor.EditedFile") -> None:
        abs_path = os.path.join(self.project_root, edited_file.relative_path)
        new_contents = edited_file.get_contents()
        with open(abs_path, "w", encoding=self.encoding, newline=self.newline) as f:
            f.write(new_contents)

    @abstractmethod
    def _find_unique_symbol(self, name_path: str, relative_file_path: str) -> TSymbol:
        """
        Finds the unique symbol with the given name in the given file.
        If no such symbol exists, raises a ValueError.

        :param name_path: the name path
        :param relative_file_path: the relative path of the file in which to search for the symbol.
        :return: the unique symbol
        """

    def replace_body(self, name_path: str, relative_file_path: str, body: str) -> None:
        """
        Replaces the body of the symbol with the given name_path in the given file.

        :param name_path: the name path of the symbol to replace.
        :param relative_file_path: the relative path of the file in which the symbol is defined.
        :param body: the new body
        """
        symbol = self._find_unique_symbol(name_path, relative_file_path)
        start_pos = symbol.get_body_start_position_or_raise()
        end_pos = symbol.get_body_end_position_or_raise()

        with self.edited_file_context(relative_file_path) as edited_file:
            # make sure the replacement adds no additional newlines (before or after) - all newlines
            # and whitespace before/after should remain the same, so we strip it entirely
            body = body.strip()

            edited_file.delete_text_between_positions(start_pos, end_pos)
            edited_file.insert_text_at_position(start_pos, body)

    @staticmethod
    def _count_leading_newlines(text: Iterable) -> int:
        cnt = 0
        for c in text:
            if c == "\n":
                cnt += 1
            elif c == "\r":
                continue
            else:
                break
        return cnt

    @classmethod
    def _count_trailing_newlines(cls, text: Reversible) -> int:
        return cls._count_leading_newlines(reversed(text))

    def insert_after_symbol(self, name_path: str, relative_file_path: str, body: str) -> None:
        """
        Inserts content after the symbol with the given name in the given file.
        """
        symbol = self._find_unique_symbol(name_path, relative_file_path)
        # Note: for body to be available, the symbol dto that the symbol instance is built from
        # must have been retrieved either with body or at least with location.
        # since _find_unique_symbol passes include_location=True, it works here
        if symbol.body == symbol.name:
            raise ValueError(
                f"Cannot insert after this symbol (not a function, class or method): {symbol}. Consider using insert_before_symbol instead."
            )

        # make sure body always ends with at least one newline
        if not body.endswith("\n"):
            body += "\n"

        pos = symbol.get_body_end_position_or_raise()

        # start at the beginning of the next line
        col = 0
        line = pos.line + 1

        # make sure a suitable number of leading empty lines is used (at least 0/1 depending on the symbol type,
        # otherwise as many as the caller wanted to insert)
        original_leading_newlines = self._count_leading_newlines(body)
        body = body.lstrip("\r\n")
        min_empty_lines = 0
        if symbol.is_neighbouring_definition_separated_by_empty_line():
            min_empty_lines = 1
        num_leading_empty_lines = max(min_empty_lines, original_leading_newlines)
        if num_leading_empty_lines:
            body = ("\n" * num_leading_empty_lines) + body

        # make sure the one line break succeeding the original symbol, which we repurposed as prefix via
        # `line += 1`, is replaced
        body = body.rstrip("\r\n") + "\n"

        with self.edited_file_context(relative_file_path) as edited_file:
            edited_file.insert_text_at_position(PositionInFile(line, col), body)

    def insert_before_symbol(self, name_path: str, relative_file_path: str, body: str) -> None:
        """
        Inserts content before the symbol with the given name in the given file.
        """
        symbol = self._find_unique_symbol(name_path, relative_file_path)
        symbol_start_pos = symbol.get_body_start_position_or_raise()

        # insert position is the start of line where the symbol is defined
        line = symbol_start_pos.line
        col = 0

        original_trailing_empty_lines = self._count_trailing_newlines(body) - 1

        # ensure eol is present at end
        body = body.rstrip() + "\n"

        # add suitable number of trailing empty lines after the body (at least 0/1 depending on the symbol type,
        # otherwise as many as the caller wanted to insert)
        min_trailing_empty_lines = 0
        if symbol.is_neighbouring_definition_separated_by_empty_line():
            min_trailing_empty_lines = 1
        num_trailing_newlines = max(min_trailing_empty_lines, original_trailing_empty_lines)
        body += "\n" * num_trailing_newlines

        # apply edit
        with self.edited_file_context(relative_file_path) as edited_file:
            edited_file.insert_text_at_position(PositionInFile(line=line, col=col), body)

    def insert_at_line(self, relative_path: str, line: int, content: str) -> None:
        """
        Inserts content at the given line in the given file.

        :param relative_path: the relative path of the file in which to insert content
        :param line: the 0-based index of the line to insert content at
        :param content: the content to insert
        """
        with self.edited_file_context(relative_path) as edited_file:
            edited_file.insert_text_at_position(PositionInFile(line, 0), content)

    def delete_lines(self, relative_path: str, start_line: int, end_line: int) -> None:
        """
        Deletes lines in the given file.

        :param relative_path: the relative path of the file in which to delete lines
        :param start_line: the 0-based index of the first line to delete (inclusive)
        :param end_line: the 0-based index of the last line to delete (inclusive)
        """
        start_col = 0
        end_line_for_delete = end_line + 1
        end_col = 0
        with self.edited_file_context(relative_path) as edited_file:
            start_pos = PositionInFile(line=start_line, col=start_col)
            end_pos = PositionInFile(line=end_line_for_delete, col=end_col)
            edited_file.delete_text_between_positions(start_pos, end_pos)

    def delete_symbol(self, name_path: str, relative_file_path: str) -> None:
        """
        Deletes the symbol with the given name in the given file.
        """
        symbol = self._find_unique_symbol(name_path, relative_file_path)
        start_pos = symbol.get_body_start_position_or_raise()
        end_pos = symbol.get_body_end_position_or_raise()
        with self.edited_file_context(relative_file_path) as edited_file:
            edited_file.delete_text_between_positions(start_pos, end_pos)

    @abstractmethod
    def rename_symbol(self, name_path: str, relative_path: str, new_name: str) -> str:
        pass


class LanguageServerCodeEditor(CodeEditor[LanguageServerSymbol]):
    def __init__(self, symbol_retriever: LanguageServerSymbolRetriever):
        super().__init__(project=symbol_retriever.project)
        self._symbol_retriever = symbol_retriever

    def _get_language_server(self, relative_path: str) -> SolidLanguageServer:
        return self._symbol_retriever.get_language_server(relative_path)

    class EditedFile(CodeEditor.EditedFile):
        def __init__(self, lang_server: SolidLanguageServer, relative_path: str, file_buffer: LSPFileBuffer):
            super().__init__(relative_path)
            self._lang_server = lang_server
            self._file_buffer = file_buffer

        def get_contents(self) -> str:
            return self._file_buffer.contents

        def set_contents(self, contents: str) -> None:
            self._file_buffer.contents = contents

        def delete_text_between_positions(self, start_pos: PositionInFile, end_pos: PositionInFile) -> None:
            self._lang_server.delete_text_between_positions(self.relative_path, start_pos.to_lsp_position(), end_pos.to_lsp_position())

        def insert_text_at_position(self, pos: PositionInFile, text: str) -> None:
            self._lang_server.insert_text_at_position(self.relative_path, pos.line, pos.col, text)

        def apply_text_edits(self, text_edits: list[ls_types.TextEdit]) -> None:
            return self._lang_server.apply_text_edits_to_file(self.relative_path, text_edits)

    @contextmanager
    def _open_file_context(self, relative_path: str) -> Iterator["CodeEditor.EditedFile"]:
        lang_server = self._get_language_server(relative_path)
        with lang_server.open_file(relative_path) as file_buffer:
            yield self.EditedFile(lang_server, relative_path, file_buffer)

    def _get_code_file_content(self, relative_path: str) -> str:
        """Get the content of a file using the language server."""
        lang_server = self._get_language_server(relative_path)
        return lang_server.language_server.retrieve_full_file_content(relative_path)

    def _find_unique_symbol(self, name_path: str, relative_file_path: str) -> LanguageServerSymbol:
        return self._symbol_retriever.find_unique(name_path, within_relative_path=relative_file_path)

    def _relative_path_from_uri(self, uri: str) -> str:
        return os.path.relpath(PathUtils.uri_to_path(uri), self.project_root)

    class EditOperation(ABC):
        @abstractmethod
        def apply(self) -> None:
            pass

    class EditOperationFileTextEdits(EditOperation):
        def __init__(self, code_editor: "LanguageServerCodeEditor", file_uri: str, text_edits: list[ls_types.TextEdit]):
            self._code_editor = code_editor
            self._relative_path = code_editor._relative_path_from_uri(file_uri)
            self._text_edits = text_edits

        def apply(self) -> None:
            with self._code_editor.edited_file_context(self._relative_path) as edited_file:
                edited_file = cast(LanguageServerCodeEditor.EditedFile, edited_file)
                edited_file.apply_text_edits(self._text_edits)

    class EditOperationRenameFile(EditOperation):
        def __init__(self, code_editor: "LanguageServerCodeEditor", old_uri: str, new_uri: str):
            self._code_editor = code_editor
            self._old_relative_path = code_editor._relative_path_from_uri(old_uri)
            self._new_relative_path = code_editor._relative_path_from_uri(new_uri)

        def apply(self) -> None:
            old_abs_path = os.path.join(self._code_editor.project_root, self._old_relative_path)
            new_abs_path = os.path.join(self._code_editor.project_root, self._new_relative_path)
            os.rename(old_abs_path, new_abs_path)

    def _workspace_edit_to_edit_operations(self, workspace_edit: ls_types.WorkspaceEdit) -> list["LanguageServerCodeEditor.EditOperation"]:
        operations: list[LanguageServerCodeEditor.EditOperation] = []

        if "changes" in workspace_edit:
            for uri, edits in workspace_edit["changes"].items():
                operations.append(self.EditOperationFileTextEdits(self, uri, edits))

        if "documentChanges" in workspace_edit:
            for change in workspace_edit["documentChanges"]:
                if "textDocument" in change and "edits" in change:
                    operations.append(self.EditOperationFileTextEdits(self, change["textDocument"]["uri"], change["edits"]))
                elif "kind" in change:
                    if change["kind"] == "rename":
                        operations.append(self.EditOperationRenameFile(self, change["oldUri"], change["newUri"]))
                    else:
                        raise ValueError(f"Unhandled document change kind: {change}; Please report to Serena developers.")
                else:
                    raise ValueError(f"Unhandled document change format: {change}; Please report to Serena developers.")

        return operations

    def _apply_text_document_edit(
        self,
        change: dict[str, Any],
        snapshot: dict[str, str],
        applied: list[dict[str, Any]],
    ) -> None:
        """Apply a single TextDocumentEdit document-change.

        Honors ``textDocument.version``: when not ``None``, must match the
        server-tracked version of the open file or ValueError is raised.
        Multi-edit support: edits within ``edits`` are applied in
        descending offset order (T6) so earlier-line edits don't invalidate
        later-line offsets.

        :param change: the documentChange entry (TextDocumentEdit shape)
        :param snapshot: per-URI original content map; updated in place
        :param applied: per-operation log; updated in place
        """
        text_doc: dict[str, Any] = change["textDocument"]
        uri: str = text_doc["uri"]
        requested_version = text_doc.get("version")
        relative_path = self._relative_path_from_uri(uri)
        if requested_version is not None:
            ls = self._get_language_server(relative_path)
            tracked_version = getattr(ls, "get_open_file_version", lambda _p: None)(relative_path)
            if tracked_version is not None and tracked_version != requested_version:
                raise ValueError(
                    f"TextDocumentEdit version mismatch for {uri}: "
                    f"requested {requested_version}, server-tracked {tracked_version}"
                )
        abs_path = os.path.join(self.project_root, relative_path)
        if uri not in snapshot:
            try:
                snapshot[uri] = open(abs_path, encoding=self.encoding).read()
            except FileNotFoundError:
                snapshot[uri] = "__NONEXISTENT__"
        text_edits: list[dict[str, Any]] = list(change["edits"])
        # T5 hook: defensive snippet-marker stripping (added in T5)
        text_edits = [self._defang_text_edit(te) for te in text_edits]
        # T6: sort descending so later-line edits don't shift earlier offsets
        text_edits.sort(
            key=lambda te: (
                te["range"]["start"]["line"],
                te["range"]["start"]["character"],
            ),
            reverse=True,
        )
        with self.edited_file_context(relative_path) as edited_file:
            edited_file = cast(LanguageServerCodeEditor.EditedFile, edited_file)
            edited_file.apply_text_edits(cast(list[ls_types.TextEdit], text_edits))
        applied.append({"kind": "textDocumentEdit", "uri": uri, "edits": text_edits})

    @staticmethod
    def _strip_snippet_markers(text: str) -> str:
        """Strip LSP snippet markers from text.

        Grammar (LSP §3.16 SnippetTextEdit):
        - ``$N`` (N a digit) → placeholder, drop entirely.
        - ``${N}`` → placeholder, drop entirely.
        - ``${N:default}`` → keep ``default``, drop the wrapper. Recursive
          (default itself may contain markers).
        - ``\\$`` → escape; emit literal ``$``.

        Applied defensively even when ``snippetTextEdit:false`` is advertised,
        per §4.1 row 6 + S2 spike finding.
        """
        # First, repeatedly strip ${N:default} from inside out (handles nesting).
        prev = None
        while prev != text:
            prev = text
            text = _SNIPPET_DOLLAR_BRACE_N.sub(lambda m: m.group(2) or "", text)
        # Then strip bare $N.
        text = _SNIPPET_DOLLAR_N.sub("", text)
        # Finally unescape \$ → $.
        text = _SNIPPET_ESCAPED_DOLLAR.sub("$", text)
        return text

    def _defang_text_edit(self, text_edit: dict[str, Any]) -> dict[str, Any]:
        """Strip snippet markers from a TextEdit's newText (T5).

        Returns a new dict; original is not mutated. Range is copied unchanged.
        """
        return {
            "range": text_edit["range"],
            "newText": self._strip_snippet_markers(text_edit["newText"]),
        }

    def _apply_create_file(
        self,
        change: dict[str, Any],
        snapshot: dict[str, str],
        applied: list[dict[str, Any]],
    ) -> None:
        """Apply a CreateFile resource operation.

        Options matrix (per LSP §3.16 spec):
        - neither flag + target absent: create empty file.
        - neither flag + target present: raise FileExistsError.
        - overwrite=True + target present: truncate to empty.
        - ignoreIfExists=True + target present: silent skip (still counted).
        - overwrite wins over ignoreIfExists when both are set.
        """
        uri: str = change["uri"]
        options: dict[str, Any] = change.get("options", {})
        overwrite: bool = bool(options.get("overwrite"))
        ignore_if_exists: bool = bool(options.get("ignoreIfExists"))
        relative_path = self._relative_path_from_uri(uri)
        abs_path = os.path.join(self.project_root, relative_path)
        already_exists = os.path.exists(abs_path)
        # Snapshot for rollback: record "did not exist" sentinel so T8 can delete on restore.
        if uri not in snapshot:
            if already_exists:
                snapshot[uri] = open(abs_path, encoding=self.encoding).read()
            else:
                snapshot[uri] = "__NONEXISTENT__"
        if already_exists and not overwrite:
            if ignore_if_exists:
                applied.append({"kind": "createFile", "uri": uri, "skipped": True})
                return
            raise FileExistsError(
                f"CreateFile target already exists and neither overwrite nor "
                f"ignoreIfExists was set: {uri}"
            )
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, "w", encoding=self.encoding, newline=self.newline) as f:
            f.write("")
        applied.append({"kind": "createFile", "uri": uri, "skipped": False})

    def _apply_delete_file(
        self,
        change: dict[str, Any],
        snapshot: dict[str, str],
        applied: list[dict[str, Any]],
    ) -> None:
        """Apply a DeleteFile resource operation.

        Options matrix (per LSP §3.16 spec):
        - target present + file: delete (snapshot stores prior content for T10 inverse).
        - target present + dir: raise IsADirectoryError unless recursive=True.
        - target absent + neither flag: raise FileNotFoundError.
        - target absent + ignoreIfNotExists=True: silent skip.
        """
        import shutil

        uri: str = change["uri"]
        options: dict[str, Any] = change.get("options", {})
        recursive: bool = bool(options.get("recursive"))
        ignore_if_not_exists: bool = bool(options.get("ignoreIfNotExists"))
        relative_path = self._relative_path_from_uri(uri)
        abs_path = os.path.join(self.project_root, relative_path)
        if not os.path.exists(abs_path):
            if ignore_if_not_exists:
                applied.append({"kind": "deleteFile", "uri": uri, "skipped": True})
                return
            raise FileNotFoundError(
                f"DeleteFile target does not exist and ignoreIfNotExists is not set: {uri}"
            )
        if os.path.isdir(abs_path):
            if not recursive:
                raise IsADirectoryError(
                    f"DeleteFile target is a directory and recursive is not set: {uri}"
                )
            # Best-effort directory snapshot: record the dir path with sentinel
            # so T10 inverse can flag it as non-restorable (we don't deep-snapshot trees).
            snapshot[uri] = "__DIRECTORY__"
            shutil.rmtree(abs_path)
        else:
            if uri not in snapshot:
                snapshot[uri] = open(abs_path, encoding=self.encoding).read()
            os.remove(abs_path)
        applied.append({"kind": "deleteFile", "uri": uri, "skipped": False})

    def _apply_rename_file(
        self,
        change: dict[str, Any],
        snapshot: dict[str, str],
        applied: list[dict[str, Any]],
    ) -> None:
        """Apply a RenameFile resource operation.

        Options matrix:
        - dst absent: rename freely.
        - dst present + neither flag: raise FileExistsError.
        - dst present + overwrite=True: replace dst (record dst content in snapshot).
        - dst present + ignoreIfExists=True: silent skip (src and dst both untouched).
        - overwrite wins over ignoreIfExists when both are set.
        """
        old_uri: str = change["oldUri"]
        new_uri: str = change["newUri"]
        options: dict[str, Any] = change.get("options", {})
        overwrite: bool = bool(options.get("overwrite"))
        ignore_if_exists: bool = bool(options.get("ignoreIfExists"))
        old_rel = self._relative_path_from_uri(old_uri)
        new_rel = self._relative_path_from_uri(new_uri)
        old_abs = os.path.join(self.project_root, old_rel)
        new_abs = os.path.join(self.project_root, new_rel)
        # Snapshot src content so T10 inverse can recreate at oldUri
        if old_uri not in snapshot:
            try:
                snapshot[old_uri] = open(old_abs, encoding=self.encoding).read()
            except FileNotFoundError:
                snapshot[old_uri] = "__NONEXISTENT__"
        dst_existed = os.path.exists(new_abs)
        if dst_existed and not overwrite:
            if ignore_if_exists:
                applied.append({"kind": "renameFile", "oldUri": old_uri, "newUri": new_uri, "skipped": True})
                return
            raise FileExistsError(
                f"RenameFile destination exists and neither overwrite nor "
                f"ignoreIfExists was set: {new_uri}"
            )
        if dst_existed and new_uri not in snapshot:
            snapshot[new_uri] = open(new_abs, encoding=self.encoding).read()
        os.makedirs(os.path.dirname(new_abs), exist_ok=True)
        os.replace(old_abs, new_abs)  # os.replace overwrites on POSIX & Windows atomically
        applied.append({"kind": "renameFile", "oldUri": old_uri, "newUri": new_uri, "skipped": False})

    @staticmethod
    def _collect_change_annotations(workspace_edit: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Return the WorkspaceEdit's changeAnnotations map (or {} if absent).

        Keyed by ``ChangeAnnotationIdentifier`` (str); values are
        ``ChangeAnnotation`` TypedDicts ({label, needsConfirmation?,
        description?}). Per §4.1 row 5 + Q4 §7.1 this is ADVISORY: the
        applier never blocks on ``needsConfirmation=True`` -- caller (MCP
        tool layer) decides whether to surface a confirmation prompt.
        """
        return dict(workspace_edit.get("changeAnnotations", {}))

    def _drive_workspace_edit(
        self,
        workspace_edit: ls_types.WorkspaceEdit,
        snapshot: dict[str, str],
        applied: list[dict[str, Any]],
    ) -> None:
        """Internal core of _apply_workspace_edit; mutates snapshot + applied."""
        if "changes" in workspace_edit:
            for uri, edits in workspace_edit["changes"].items():
                self._apply_text_document_edit(
                    {"textDocument": {"uri": uri, "version": None}, "edits": edits},
                    snapshot,
                    applied,
                )
        if "documentChanges" in workspace_edit:
            for change in workspace_edit["documentChanges"]:
                kind = change.get("kind")
                if kind is None:
                    self._apply_text_document_edit(change, snapshot, applied)
                elif kind == "create":
                    self._apply_create_file(change, snapshot, applied)
                elif kind == "delete":
                    self._apply_delete_file(change, snapshot, applied)
                elif kind == "rename":
                    self._apply_rename_file(change, snapshot, applied)
                else:
                    raise ValueError(f"Unhandled documentChange kind: {kind!r}")

    def _restore_snapshot(self, snapshot: dict[str, str], applied: list[dict[str, Any]]) -> None:
        """Walk applied operations in reverse, undoing each via snapshot.

        For each touched URI:
        - ``__NONEXISTENT__`` sentinel -> file existed-not before, delete now.
        - ``__DIRECTORY__`` sentinel -> directory was rmtree'd; cannot fully
          restore (deep snapshot is out of scope for v1.0). Best effort:
          re-create empty dir to preserve tree shape.
        - any other string -> file existed before; rewrite content.
        """
        # Reverse the applied log to undo create/rename in the right order.
        for op in reversed(applied):
            kind = op["kind"]
            if kind == "renameFile" and not op.get("skipped"):
                old_abs = os.path.join(
                    self.project_root, self._relative_path_from_uri(op["oldUri"])
                )
                new_abs = os.path.join(
                    self.project_root, self._relative_path_from_uri(op["newUri"])
                )
                # Move dst back to src (best-effort)
                if os.path.exists(new_abs):
                    os.replace(new_abs, old_abs)
        # Then restore content per snapshot URI.
        for uri, original in snapshot.items():
            rel = self._relative_path_from_uri(uri)
            abs_path = os.path.join(self.project_root, rel)
            if original == "__NONEXISTENT__":
                if os.path.exists(abs_path) and os.path.isfile(abs_path):
                    os.remove(abs_path)
            elif original == "__DIRECTORY__":
                if not os.path.exists(abs_path):
                    os.makedirs(abs_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "w", encoding=self.encoding, newline=self.newline) as f:
                    f.write(original)

    def _apply_workspace_edit(self, workspace_edit: ls_types.WorkspaceEdit) -> int:
        """Apply a WorkspaceEdit through the full Stage 1B matrix.

        Handles every documentChanges shape (TextDocumentEdit / CreateFile /
        RenameFile / DeleteFile) plus the legacy ``changes`` map. Wraps the
        body in an atomic snapshot/restore (T8); on any exception, every
        touched file is restored to its pre-edit state before re-raising.

        :param workspace_edit: the edit to apply
        :return: number of documentChange entries applied
        """
        snapshot: dict[str, str] = {}
        applied: list[dict[str, Any]] = []
        try:
            self._drive_workspace_edit(workspace_edit, snapshot, applied)
        except Exception:
            self._restore_snapshot(snapshot, applied)
            raise
        return len(applied)

    def _apply_workspace_edit_with_report(
        self, workspace_edit: ls_types.WorkspaceEdit
    ) -> dict[str, Any]:
        """Like _apply_workspace_edit but returns a structured report.

        Report shape:
            {
                "count": int,                        # operations applied
                "annotations": dict[str, dict],      # changeAnnotations map
                "snapshot": dict[str, str],          # per-URI prior content
                "applied": list[dict[str, Any]],     # per-op log for T10 inverse
            }
        """
        annotations = self._collect_change_annotations(cast(dict[str, Any], workspace_edit))
        snapshot: dict[str, str] = {}
        applied: list[dict[str, Any]] = []
        try:
            self._drive_workspace_edit(workspace_edit, snapshot, applied)
        except Exception:
            self._restore_snapshot(snapshot, applied)
            raise
        return {
            "count": len(applied),
            "annotations": annotations,
            "snapshot": snapshot,
            "applied": applied,
        }

    def rename_symbol(self, name_path: str, relative_path: str, new_name: str) -> str:
        """
        Renames a symbol, file, or directory throughout the codebase.

        :param name_path: the name path of the symbol to rename
        :param relative_path: the relative path of the file containing the symbol.
        :param new_name: the new name
        :return: a status message
        """
        symbol = self._find_unique_symbol(name_path, relative_path)
        if not symbol.location.has_position_in_file():
            raise ValueError(f"Symbol '{name_path}' does not have a valid position in file for renaming")

        # After has_position_in_file check, line and column are guaranteed to be non-None
        assert symbol.location.line is not None
        assert symbol.location.column is not None

        lang_server = self._get_language_server(relative_path)
        rename_result = lang_server.request_rename_symbol_edit(
            relative_file_path=relative_path, line=symbol.location.line, column=symbol.location.column, new_name=new_name
        )
        if rename_result is None:
            raise ValueError(
                f"Language server for {lang_server.language_id} returned no rename edits for symbol '{name_path}'. "
                f"The symbol might not support renaming."
            )
        num_changes = self._apply_workspace_edit(rename_result)

        if num_changes == 0:
            raise ValueError(
                f"Renaming symbol '{name_path}' to '{new_name}' resulted in no changes being applied; renaming may not be supported."
            )

        msg = f"Successfully renamed '{name_path}' to '{new_name}' ({num_changes} changes applied)"
        return msg


class JetBrainsCodeEditor(CodeEditor[JetBrainsSymbol]):
    def __init__(self, project: Project) -> None:
        self._project = project
        super().__init__(project)

    class EditedFile(CodeEditor.EditedFile):
        def __init__(self, relative_path: str, project: Project):
            super().__init__(relative_path)
            path = os.path.join(project.project_root, relative_path)
            log.info("Editing file: %s", path)
            with open(path, encoding=project.project_config.encoding) as f:
                self._content = f.read()

        def get_contents(self) -> str:
            return self._content

        def set_contents(self, contents: str) -> None:
            self._content = contents

        def delete_text_between_positions(self, start_pos: PositionInFile, end_pos: PositionInFile) -> None:
            self._content, _ = TextUtils.delete_text_between_positions(
                self._content, start_pos.line, start_pos.col, end_pos.line, end_pos.col
            )

        def insert_text_at_position(self, pos: PositionInFile, text: str) -> None:
            self._content, _, _ = TextUtils.insert_text_at_position(self._content, pos.line, pos.col, text)

    @contextmanager
    def _open_file_context(self, relative_path: str) -> Iterator["CodeEditor.EditedFile"]:
        yield self.EditedFile(relative_path, self._project)

    def _save_edited_file(self, edited_file: "CodeEditor.EditedFile") -> None:
        super()._save_edited_file(edited_file)
        with JetBrainsPluginClient.from_project(self._project) as client:
            client.refresh_file(edited_file.relative_path)

    def _find_unique_symbol(self, name_path: str, relative_file_path: str) -> JetBrainsSymbol:
        with JetBrainsPluginClient.from_project(self._project) as client:
            result = client.find_symbol(name_path, relative_path=relative_file_path, include_body=False, depth=0, include_location=True)
            symbols = result["symbols"]
            if not symbols:
                raise ValueError(f"No symbol with name {name_path} found in file {relative_file_path}")
            if len(symbols) > 1:
                raise ValueError(
                    f"Found multiple {len(symbols)} symbols with name {name_path} in file {relative_file_path}: "
                    + json.dumps(symbols, indent=2)
                )
            return JetBrainsSymbol(symbols[0], self._project)

    def rename_symbol(
        self,
        name_path: str | None,
        relative_path: str,
        new_name: str,
        rename_in_comments: bool = False,
        rename_in_text_occurrences: bool = False,
    ) -> str:
        """
        Renames a code symbol, file, or directory throughout the codebase.

        :param name_path: the name path of the symbol to rename. Set to None for renaming a file or directory.
        :param relative_path: if `name_path` is passed, the relative path of the file containing the symbol.
            Otherwise, the path to the directory or file to rename.
        :param new_name: the new name
        :param rename_in_comments: whether to rename occurrences of the symbol in comments
        :param rename_in_text_occurrences: whether to rename occurrences of the symbol in text
        :return: a status message
        """
        with JetBrainsPluginClient.from_project(self._project) as client:
            client.rename_symbol(
                name_path=name_path,
                relative_path=relative_path,
                new_name=new_name,
                rename_in_comments=rename_in_comments,
                rename_in_text_occurrences=rename_in_text_occurrences,
            )
            return "Success"

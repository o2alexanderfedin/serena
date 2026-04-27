"""basedpyright adapter — Stage 1E §14.1 file 16.

Phase 0 P4 contract:
  - basedpyright 1.39.3 (Phase 0 Q3 pin) is PULL-mode only — emits ZERO
    publishDiagnostics. Consumers must call ``textDocument/diagnostic``.
  - basedpyright BLOCKS on server->client requests if unanswered. The base
    ``_install_default_request_handlers`` already auto-responds to
    workspace/configuration (-> ``[{} for _ in items]``),
    client/registerCapability (-> null), client/unregisterCapability (-> null),
    window/workDoneProgress/create (-> null), so this adapter does NOT need
    to override any handler.
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Any, ClassVar, cast

from overrides import override

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.lsp_protocol_handler.server import ProcessLaunchInfo
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)

BASEDPYRIGHT_VERSION_PIN: str = "1.39.3"  # Phase 0 Q3.


class BasedpyrightServer(SolidLanguageServer):
    """basedpyright-langserver adapter — pull-mode diagnostics."""

    server_id: ClassVar[str] = "basedpyright"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd="basedpyright-langserver --stdio",
                cwd=repository_root_path,
            ),
            "python",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        # Stage 1E: BasedpyrightServer is registered by PythonStrategy (T7)
        # rather than via the legacy ``Language.get_ls_class()`` registry,
        # which currently maps ``Language.PYTHON`` to ``PyrightServer``.
        # Returning ``Language.PYTHON`` here gives the base class the
        # language identity it needs without forcing a registry mutation
        # that would collide with PyrightServer.
        return Language.PYTHON

    @override
    def is_ignored_dirname(self, dirname: str) -> bool:
        return super().is_ignored_dirname(dirname) or dirname in (
            "venv",
            ".venv",
            "__pycache__",
            ".tox",
            ".mypy_cache",
            ".ruff_cache",
        )

    @staticmethod
    def _get_initialize_params(repository_absolute_path: str) -> InitializeParams:
        root_uri = pathlib.Path(repository_absolute_path).as_uri()
        params: dict[str, Any] = {
            "processId": os.getpid(),
            "clientInfo": {"name": "Serena", "version": "0.1.0"},
            "locale": "en",
            "rootPath": repository_absolute_path,
            "rootUri": root_uri,
            "capabilities": {
                "workspace": {
                    "configuration": True,
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    # P4: basedpyright dynamically registers
                    # textDocument/diagnostic via client/registerCapability —
                    # we accept this passively (base auto-responder).
                    "diagnostics": {"refreshSupport": True, "relatedDocumentSupport": True},
                },
                "textDocument": {
                    "synchronization": {
                        "dynamicRegistration": True,
                        "didSave": True,
                        "willSave": False,
                        "willSaveWaitUntil": False,
                    },
                    # Pull-mode opt-in.
                    "diagnostic": {
                        "dynamicRegistration": True,
                        "relatedDocumentSupport": True,
                    },
                    "publishDiagnostics": {
                        # We still advertise — basedpyright never sends, but
                        # downgrading the capability would surprise other
                        # clients sharing this base class.
                        "relatedInformation": True,
                    },
                },
                "window": {"workDoneProgress": True},
            },
            "initializationOptions": {
                "python": {
                    # T8 will set this to the resolved interpreter via
                    # configure_python_path(); blank here is fine — pyright
                    # falls back to sys.executable.
                    "pythonPath": "",
                },
            },
            "workspaceFolders": [
                {"uri": root_uri, "name": pathlib.Path(repository_absolute_path).name}
            ],
        }
        return cast(InitializeParams, params)

    def _start_server(self) -> None:
        """Boot basedpyright: start subprocess, send initialize, send initialized.

        Reverse-request handlers (workspace/configuration, client/registerCapability,
        client/unregisterCapability, window/workDoneProgress/create) are already
        installed by the base class via ``_install_default_request_handlers()``
        at __init__ time — basedpyright would BLOCK on any of these if unanswered
        (Phase 0 P4), so the base auto-responder is load-bearing.
        """
        log.info("Starting basedpyright-langserver process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)
        log.info("Sending initialize request to basedpyright")
        self.server.send.initialize(initialize_params)
        self.server.notify.initialized({})

    # ------------------------------------------------------------------
    # P4 pull-mode facade.
    # ------------------------------------------------------------------

    def request_pull_diagnostics(self, uri: str) -> dict[str, Any]:
        """Send ``textDocument/diagnostic`` and return the response.

        Per LSP §3.17 ``textDocument/diagnostic`` returns a
        ``RelatedFullDocumentDiagnosticReport`` (kind=full + items[]) or a
        ``RelatedUnchangedDocumentDiagnosticReport`` (kind=unchanged +
        resultId). Caller inspects ``kind``; on ``unchanged`` reuse the
        previous items.

        :param uri: file URI of the document to diagnose.
        :return: the raw response dict from basedpyright.
        """
        params = {"textDocument": {"uri": uri}}
        response = self.server.send_request("textDocument/diagnostic", params)
        return cast(dict[str, Any], response or {})

    def configure_python_path(self, python_path: str) -> None:
        """Push the resolved interpreter into basedpyright via didChangeConfiguration.

        T8 calls this once after the 14-step interpreter discovery resolves.
        Sent post-initialize because pythonPath in initializationOptions does
        not always re-trigger workspace re-analysis on basedpyright 1.39.3.
        """
        notif = {
            "settings": {"python": {"pythonPath": python_path}},
        }
        self.server.send_notification("workspace/didChangeConfiguration", notif)

"""ruff native LSP adapter — Stage 1E §14.1 file 17.

ruff >=0.6.0 ships a native LSP (``ruff server``) that pushes diagnostics
in standard LSP shape; no pull-mode. Per Phase 0 P2, ruff wins
``source.organizeImports`` at the merge layer — adapter does not need to
know; priority lives in ``multi_server.py``.
"""

from __future__ import annotations

import logging
import os
import pathlib
from typing import Any, cast

from overrides import override

from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.lsp_protocol_handler.server import ProcessLaunchInfo
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)


class RuffServer(SolidLanguageServer):
    """ruff native LSP adapter (push-mode diagnostics)."""

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(cmd="ruff server", cwd=repository_root_path),
            "python",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        # Stage 1E: RuffServer is registered by PythonStrategy (T7) rather
        # than via the legacy ``Language.get_ls_class()`` registry, which
        # currently maps ``Language.PYTHON`` to ``PyrightServer``.
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
                },
                "textDocument": {
                    "synchronization": {
                        "dynamicRegistration": True,
                        "didSave": True,
                    },
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "tagSupport": {"valueSet": [1, 2]},
                        "codeDescriptionSupport": True,
                    },
                    "codeAction": {
                        "dynamicRegistration": True,
                        "isPreferredSupport": True,
                        "disabledSupport": True,
                        "dataSupport": True,
                        "resolveSupport": {"properties": ["edit"]},
                        "codeActionLiteralSupport": {
                            "codeActionKind": {
                                "valueSet": [
                                    "",
                                    "quickfix",
                                    "source",
                                    "source.organizeImports",
                                    "source.fixAll",
                                ]
                            }
                        },
                    },
                },
            },
            "workspaceFolders": [
                {"uri": root_uri, "name": pathlib.Path(repository_absolute_path).name}
            ],
        }
        return cast(InitializeParams, params)

    def _start_server(self) -> None:
        """Boot ruff: start subprocess, send initialize, send initialized.

        Reverse-request handlers (workspace/configuration, client/registerCapability,
        client/unregisterCapability, window/workDoneProgress/create) are already
        installed by the base class via ``_install_default_request_handlers()``
        at __init__ time. ruff's native server speaks standard LSP and does not
        require any server-specific notification handlers beyond the LSP defaults.
        """
        log.info("Starting ruff server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)
        log.info("Sending initialize request to ruff")
        self.server.send.initialize(initialize_params)
        self.server.notify.initialized({})

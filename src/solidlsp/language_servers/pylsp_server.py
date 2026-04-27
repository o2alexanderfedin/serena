"""python-lsp-server (pylsp) + pylsp-rope adapter — Stage 1E §14.1 file 15.

Launches ``python -m pylsp --check-parent-process`` over stdio. The
``pylsp-rope`` plugin is auto-discovered when installed in the same
interpreter (entry-point group ``pylsp``); no extra wiring required at
the LSP level.

This module ships in two stages:
  - T3 (this file): spawn + initialize + facade conformance.
  - T4 (next file revision): override ``execute_command`` to drain
    ``workspace/applyEdit`` payloads emitted *during* command execution
    (Phase 0 P1 finding — pylsp-rope ships its inline/refactor
    ``WorkspaceEdit`` via the reverse-request channel).

pylsp-mypy is enabled with live_mode=false + dmypy=true per P5a re-run outcome B (stale 0.00%, p95 2.668s); see solidlsp.decisions.p5a_mypy.
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys
from typing import Any, ClassVar, cast

from overrides import override

from solidlsp.decisions.p5a_mypy import P5A_MYPY_DECISION
from solidlsp.ls import SolidLanguageServer
from solidlsp.ls_config import Language, LanguageServerConfig
from solidlsp.lsp_protocol_handler.lsp_types import InitializeParams
from solidlsp.lsp_protocol_handler.server import ProcessLaunchInfo
from solidlsp.settings import SolidLSPSettings

log = logging.getLogger(__name__)


# Mirrors jedi_server.py InitializeParams shape; deliberately duplicated
# rather than abstracted — only two Python LSPs use this shape (jedi/pylsp)
# and basedpyright/ruff have meaningfully different capability sets.
class PylspServer(SolidLanguageServer):
    """python-lsp-server adapter (with pylsp-rope plugin auto-discovered)."""

    server_id: ClassVar[str] = "pylsp-base"

    def __init__(
        self,
        config: LanguageServerConfig,
        repository_root_path: str,
        solidlsp_settings: SolidLSPSettings,
    ) -> None:
        # Use ``sys.executable -m pylsp`` rather than the bare ``pylsp`` entry
        # point so the Stage 1E interpreter discovery (T8) can override which
        # Python pylsp-rope sees by swapping the launch command.
        super().__init__(
            config,
            repository_root_path,
            ProcessLaunchInfo(
                cmd=f"{sys.executable} -m pylsp --check-parent-process",
                cwd=repository_root_path,
            ),
            "python",
            solidlsp_settings,
        )

    @classmethod
    @override
    def get_language_enum_instance(cls) -> Language:
        # Stage 1E: PylspServer is registered by PythonStrategy (T7) rather
        # than via the legacy ``Language.get_ls_class()`` registry, which
        # currently maps ``Language.PYTHON`` to ``PyrightServer``. Returning
        # ``Language.PYTHON`` here gives the base class the language identity
        # it needs (cache dir, source-file matcher) without forcing a registry
        # mutation that would collide with PyrightServer.
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
        """Standard pylsp InitializeParams — mirrors jedi_server.py shape."""
        root_uri = pathlib.Path(repository_absolute_path).as_uri()
        params: dict[str, Any] = {
            "processId": os.getpid(),
            "clientInfo": {"name": "Serena", "version": "0.1.0"},
            "locale": "en",
            "rootPath": repository_absolute_path,
            "rootUri": root_uri,
            "capabilities": {
                "workspace": {
                    "applyEdit": True,
                    "workspaceEdit": {
                        "documentChanges": True,
                        "resourceOperations": ["create", "rename", "delete"],
                        "failureHandling": "textOnlyTransactional",
                    },
                    "configuration": True,
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    "executeCommand": {"dynamicRegistration": True},
                },
                "textDocument": {
                    "publishDiagnostics": {
                        "relatedInformation": True,
                        "tagSupport": {"valueSet": [1, 2]},
                    },
                    "synchronization": {
                        "dynamicRegistration": True,
                        "willSave": False,
                        "willSaveWaitUntil": False,
                        "didSave": True,
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
                                    "refactor",
                                    "refactor.extract",
                                    "refactor.inline",
                                    "refactor.rewrite",
                                    "source",
                                    "source.organizeImports",
                                ]
                            }
                        },
                    },
                    "rename": {"dynamicRegistration": True, "prepareSupport": True},
                },
            },
            # pylsp-rope is auto-discovered; only declare plugin toggles that
            # override defaults. Owned by `solidlsp.decisions.p5a_mypy` so any
            # future re-flip is gated by `test/decisions/test_p5a_mypy_decision.py`.
            "initializationOptions": P5A_MYPY_DECISION.pylsp_initialization_options,
            "workspaceFolders": [
                {"uri": root_uri, "name": pathlib.Path(repository_absolute_path).name}
            ],
        }
        return cast(InitializeParams, params)

    def _start_server(self) -> None:
        """Boot pylsp: start subprocess, send initialize, send initialized.

        Reverse-request handlers (workspace/applyEdit, workspace/configuration,
        client/registerCapability, etc.) are already installed by the base
        class via ``_install_default_request_handlers()`` at __init__ time
        (ls.py:581). pylsp does not require server-specific notifications
        beyond the LSP defaults.
        """
        log.info("Starting pylsp server process")
        self.server.start()
        initialize_params = self._get_initialize_params(self.repository_root_path)
        log.info("Sending initialize request to pylsp")
        self.server.send.initialize(initialize_params)
        self.server.notify.initialized({})

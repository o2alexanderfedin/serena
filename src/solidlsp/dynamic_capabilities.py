"""Per-server dynamic-capability registry, populated from
`client/registerCapability` events at runtime (LSP 3.17 §10.6).

Scope of correctness: registry holds rich registration entries keyed by
registration ``id``; method-name deduplication is by ``id`` (the server
assigns the id and is responsible for uniqueness).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass(frozen=True)
class DynamicRegistration:
    """Immutable record for a single ``client/registerCapability`` registration.

    :param id: Unique registration identifier assigned by the server.
               Required for ``client/unregisterCapability``.
    :param method: Full LSP method string, e.g. ``"textDocument/codeAction"``.
    :param register_options: Optional ``registerOptions`` dict from the
                             registration payload, which may include
                             ``documentSelector``, ``codeActionKinds``, etc.
                             Stored verbatim for future per-document gating;
                             not yet consulted by :meth:`DynamicCapabilityRegistry.has`.
    """

    id: str
    method: str
    register_options: Mapping[str, Any] = field(default_factory=dict)


class DynamicCapabilityRegistry:
    """Thread-safe per-server registry for dynamic LSP capability registrations.

    Internal shape: ``dict[server_id, dict[registration_id, DynamicRegistration]]``.

    Keys are server identifiers (e.g. ``"basedpyright"``, ``"ruff"``);
    values are maps from registration ``id`` to rich :class:`DynamicRegistration`
    records.  Registering the same ``id`` again overwrites the previous entry
    (the server reassigns the id on re-registration per LSP spec).
    """

    def __init__(self) -> None:
        self._by_server: dict[str, dict[str, DynamicRegistration]] = {}
        self._lock: Lock = Lock()

    def register(
        self,
        server_id: str,
        registration_id: str,
        method: str,
        register_options: Mapping[str, Any] | None = None,
    ) -> None:
        """Record a capability registration.

        :param server_id: Adapter-level server identifier.
        :param registration_id: Unique ``id`` from the LSP ``Registration`` object.
        :param method: LSP method string (e.g. ``"textDocument/codeAction"``).
        :param register_options: Optional ``registerOptions`` mapping from the
                                  registration payload.
        """
        entry = DynamicRegistration(
            id=registration_id,
            method=method,
            register_options=register_options or {},
        )
        with self._lock:
            self._by_server.setdefault(server_id, {})[registration_id] = entry

    def unregister(self, server_id: str, registration_id: str) -> None:
        """Remove a registration by id; idempotent.

        :param server_id: Adapter-level server identifier.
        :param registration_id: The ``id`` originally supplied in the
                                ``client/registerCapability`` request.
        """
        with self._lock:
            _ = self._by_server.get(server_id, {}).pop(registration_id, None)

    def has(self, server_id: str, method: str) -> bool:
        """Return ``True`` if *any* active registration for *server_id* covers *method*.

        Complexity: O(k) where k is the count of active registrations for the
        server, not the total number of distinct methods ever registered.

        :param server_id: Adapter-level server identifier.
        :param method: LSP method string to check.
        """
        with self._lock:
            regs = self._by_server.get(server_id, {})
            return any(r.method == method for r in regs.values())

    def list_for(self, server_id: str) -> list[str]:
        """Return deduplicated method names for *server_id*.

        Preserved for backward compatibility with :class:`LanguageHealth`
        consumers that display ``dynamic_capabilities`` as a string list.
        """
        with self._lock:
            regs = self._by_server.get(server_id, {})
            seen: set[str] = set()
            result: list[str] = []
            for r in regs.values():
                if r.method not in seen:
                    seen.add(r.method)
                    result.append(r.method)
            return result

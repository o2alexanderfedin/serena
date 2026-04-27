"""Per-server dynamic-capability registry, populated from
`client/registerCapability` events at runtime (LSP 3.17 §10.6).

Scope of correctness: registry holds string method names only;
client decides whether a method counts toward `capabilities_count`.
"""
from __future__ import annotations

from threading import Lock


class DynamicCapabilityRegistry:
    """Append-only, thread-safe per-server registry.

    Keys are server identifiers (e.g. ``"basedpyright"``, ``"ruff"``);
    values are the LSP method names the server registered dynamically.
    Duplicate registrations are deduplicated.
    """

    def __init__(self) -> None:
        self._by_server: dict[str, list[str]] = {}
        self._lock = Lock()

    def register(self, server_id: str, method: str) -> None:
        with self._lock:
            existing = self._by_server.setdefault(server_id, [])
            if method not in existing:
                existing.append(method)

    def list_for(self, server_id: str) -> list[str]:
        with self._lock:
            return list(self._by_server.get(server_id, []))

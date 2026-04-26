"""Stage 1F — capability catalog assembly + drift CI gate.

The capability catalog is the static, introspected map of every refactor /
code-action surface the o2.scalpel MCP server exposes. It is built by
walking ``STRATEGY_REGISTRY`` (Stage 1E) and intersecting each strategy's
``code_action_allow_list`` with the kinds advertised by the strategy's
adapter classes via ``codeActionLiteralSupport.codeActionKind.valueSet``.

Stage 1F delivers only the catalog + the drift gate; Stage 1G wraps the
catalog as the ``scalpel_capabilities_list`` / ``scalpel_capability_describe``
MCP tools (file 16 of §14.1).

Three exports:
  - ``CapabilityRecord`` — pydantic v2 immutable model for one row.
  - ``CapabilityCatalog`` — immutable container with deterministic JSON
    serialisation (sorted records, sort_keys, trailing newline).
  - ``build_capability_catalog`` — the factory; T2 + T3 fill it in.

Source-of-truth: ``docs/design/mvp/2026-04-24-mvp-scope-report.md`` §12.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .multi_server import ProvenanceLiteral


class CapabilityRecord(BaseModel):
    """One row of the capability catalog.

    Stage 1F superset of §12.1 ``CapabilityDescriptor``:
      - adds ``extension_allow_list`` (per-language file-suffix gate).
      - omits ``applies_to_kinds`` (deferred to Stage 2A; symbol-kind
        taxonomy not built at MVP).
      - keeps ``preferred_facade`` as ``None`` placeholder until Stage 2A
        ergonomic facades land (forward-compatible schema).

    Frozen: a record is identity once built. Catalog mutations happen by
    rebuilding the catalog from scratch via ``build_capability_catalog``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    language: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    source_server: ProvenanceLiteral
    params_schema: Mapping[str, Any] = Field(default_factory=dict)
    preferred_facade: str | None = None
    extension_allow_list: frozenset[str] = Field(default_factory=frozenset)

    @field_serializer("extension_allow_list")
    def _serialize_extensions(self, value: frozenset[str]) -> list[str]:
        # JSON has no frozenset; emit a sorted list so the baseline is stable.
        return sorted(value)

    @field_serializer("params_schema")
    def _serialize_params(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return dict(value)


class CapabilityCatalog(BaseModel):
    """Immutable container of ``CapabilityRecord`` rows.

    Sort invariant: records are kept in ``(language, source_server, kind, id)``
    order so the ``to_json`` output is byte-stable across runs and the
    checked-in golden file diffs cleanly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    records: tuple[CapabilityRecord, ...] = Field(default_factory=tuple)

    def model_post_init(self, __context: Any) -> None:
        # Re-sort on construction so every catalog (built by factory or
        # loaded from JSON) shares the same iteration order.
        sorted_records = tuple(
            sorted(
                self.records,
                key=lambda r: (r.language, r.source_server, r.kind, r.id),
            )
        )
        if sorted_records != self.records:
            # Frozen — bypass attribute assignment via __dict__ once.
            object.__setattr__(self, "records", sorted_records)

    def to_json(self) -> str:
        """Return canonical JSON: indent=2, sort_keys, trailing newline."""
        payload = {
            "schema_version": 1,
            "records": [r.model_dump(mode="json") for r in self.records],
        }
        return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"

    @classmethod
    def from_json(cls, blob: str) -> "CapabilityCatalog":
        payload = json.loads(blob)
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError(
                "capability catalog JSON missing schema_version=1; "
                "regenerate via `pytest --update-catalog-baseline`"
            )
        records = tuple(
            CapabilityRecord(
                id=r["id"],
                language=r["language"],
                kind=r["kind"],
                source_server=r["source_server"],
                params_schema=r.get("params_schema", {}),
                preferred_facade=r.get("preferred_facade"),
                extension_allow_list=frozenset(r.get("extension_allow_list", [])),
            )
            for r in payload.get("records", [])
        )
        return cls(records=records)


def build_capability_catalog(
    strategy_registry: Mapping[Any, type] | None = None,
    *,
    project_root: Any = None,
) -> CapabilityCatalog:
    """Stage 1F factory — T2 fills in the strategy walk; T3 adds adapter introspection.

    Stage 1F T1 lands a stub that returns an empty catalog so the schema
    tests can assert importability without forcing a strategy-walk. T2's
    failing test is what drives the real implementation.
    """
    del strategy_registry
    del project_root
    return CapabilityCatalog(records=())

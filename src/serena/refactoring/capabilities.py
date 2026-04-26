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
from typing import Any, Mapping, get_args

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .multi_server import ProvenanceLiteral

# Default per-language source_server attribution for the T2 strategy-only
# walk. T3 enriches this by reading the adapter codeActionKind valueSet
# to attribute kinds that ruff or basedpyright also advertise.
_DEFAULT_SOURCE_SERVER_BY_LANGUAGE: dict[str, ProvenanceLiteral] = {
    "python": "pylsp-rope",
    "rust": "rust-analyzer",
}


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
    """Walk ``STRATEGY_REGISTRY`` and emit one ``CapabilityRecord`` per
    ``(strategy.language_id, kind)`` pair.

    T2 contract — strategy-only:
      - source_server is taken from ``_DEFAULT_SOURCE_SERVER_BY_LANGUAGE``
        keyed by ``strategy.language_id``.
      - extension_allow_list is taken from ``strategy.extension_allow_list``.
      - kind is each entry of ``strategy.code_action_allow_list``.
      - id is ``f"{language}.{kind}"``.

    T3 will overlay adapter-advertised kinds and re-attribute the
    source_server when an adapter specifically advertises a kind.

    :param strategy_registry: ``{Language: StrategyClass}`` from Stage 1E.
        ``None`` is treated as an empty mapping (catalog has zero records).
    :param project_root: reserved for T8 of Stage 1G when per-project
        capability gating lands; ignored at MVP.
    """
    del project_root
    if strategy_registry is None:
        return CapabilityCatalog(records=())

    legal_servers = set(get_args(ProvenanceLiteral))
    records: list[CapabilityRecord] = []
    for _language_enum, strategy_cls in strategy_registry.items():
        language_id = strategy_cls.language_id
        source_server = _DEFAULT_SOURCE_SERVER_BY_LANGUAGE.get(language_id)
        if source_server is None or source_server not in legal_servers:
            raise ValueError(
                f"capability catalog: no default source_server registered "
                f"for language_id={language_id!r}; add it to "
                f"_DEFAULT_SOURCE_SERVER_BY_LANGUAGE"
            )
        for kind in strategy_cls.code_action_allow_list:
            records.append(
                CapabilityRecord(
                    id=f"{language_id}.{kind}",
                    language=language_id,
                    kind=kind,
                    source_server=source_server,
                    params_schema={},
                    preferred_facade=None,
                    extension_allow_list=strategy_cls.extension_allow_list,
                )
            )
    return CapabilityCatalog(records=tuple(records))

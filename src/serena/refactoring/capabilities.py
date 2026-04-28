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

import hashlib
import inspect
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
    "markdown": "marksman",
    "typescript": "vtsls",
}


class CatalogIntrospectionError(RuntimeError):
    """Raised when an adapter cannot be introspected for codeAction kinds.

    Stage 1F's contract is *static* introspection: the adapter's
    ``_get_initialize_params`` MUST be a ``@staticmethod`` so it can be
    invoked on the class without booting a server. If this invariant
    breaks, the error message points at the offending adapter and tells
    the maintainer how to fix it.
    """


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
        del __context
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

    def hash(self) -> str:
        """Return SHA-256 hex digest of canonical JSON (``to_json``).

        Stable across construction orders because ``model_post_init``
        canonicalises record order; consumers can compare hashes to detect
        catalog drift without re-serialising the records themselves.
        """
        return hashlib.sha256(self.to_json().encode()).hexdigest()

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


# Per-server adapter classes. Stage 1F walks these to extract each adapter's
# advertised codeActionKind.valueSet. Adding a new server requires:
#   1. Add an entry here mapping the ProvenanceLiteral to the adapter class.
#   2. Re-run pytest --update-catalog-baseline to refresh the golden file.
#   3. Commit the regenerated baseline alongside the adapter change.
def _adapter_map() -> dict[ProvenanceLiteral, type]:
    """Lazy import to avoid forcing solidlsp adapter modules at import time."""
    from solidlsp.language_servers.basedpyright_server import BasedpyrightServer
    from solidlsp.language_servers.pylsp_server import PylspServer
    from solidlsp.language_servers.ruff_server import RuffServer
    from solidlsp.language_servers.rust_analyzer import RustAnalyzer
    from solidlsp.language_servers.vtsls_server import VtslsServer
    return {
        "pylsp-rope": PylspServer,
        "basedpyright": BasedpyrightServer,
        "ruff": RuffServer,
        "rust-analyzer": RustAnalyzer,
        "vtsls": VtslsServer,
    }


# Per-language ordered preference for adapter attribution. When multiple
# adapters advertise the same kind, the first one in this tuple wins —
# this matches the Stage 1D _apply_priority() merge order so the catalog
# and the live merger never disagree on attribution.
_ADAPTER_ATTRIBUTION_ORDER: dict[str, tuple[ProvenanceLiteral, ...]] = {
    "python": ("ruff", "pylsp-rope", "basedpyright"),
    "rust": ("rust-analyzer",),
    "typescript": ("vtsls",),
}


def _introspect_adapter_kinds(
    adapter_cls: type, *, repository_absolute_path: str
) -> frozenset[str]:
    """Extract ``codeActionLiteralSupport.codeActionKind.valueSet`` from an adapter.

    The adapter's ``_get_initialize_params`` MUST be a ``@staticmethod``
    so we can invoke it on the class object without spawning the LSP
    process. If it is not, ``CatalogIntrospectionError`` is raised with
    a fix-it message.

    The empty string ``""`` (a valid LSP codeActionKind sentinel meaning
    "any kind") is filtered out — the catalog records concrete kinds only.

    :param adapter_cls: e.g. ``PylspServer`` (the *class*, not an instance).
    :param repository_absolute_path: any path; the helper passes it through
        to the adapter's static method but the result is independent of the
        path for every Stage 1E adapter.
    :return: frozenset of advertised concrete codeActionKind strings.
    """
    static = inspect.getattr_static(adapter_cls, "_get_initialize_params")
    if not isinstance(static, staticmethod):
        raise CatalogIntrospectionError(
            f"{adapter_cls.__name__}._get_initialize_params is not a "
            f"staticmethod; Stage 1F catalog introspection requires it to "
            f"be one (so the adapter can be queried without booting the "
            f"LSP). Refactor the adapter to use @staticmethod."
        )
    params = adapter_cls._get_initialize_params(repository_absolute_path)
    text_doc = params.get("capabilities", {}).get("textDocument", {})
    code_action = text_doc.get("codeAction", {})
    literal = code_action.get("codeActionLiteralSupport", {})
    kind = literal.get("codeActionKind", {})
    value_set = kind.get("valueSet", [])
    return frozenset(k for k in value_set if k != "")


def build_capability_catalog(
    strategy_registry: Mapping[Any, type] | None = None,
    *,
    project_root: Any = None,
) -> CapabilityCatalog:
    """Walk strategies + adapters to build the catalog.

    For each (strategy, kind) pair:
      1. Compute attribution by walking ``_ADAPTER_ATTRIBUTION_ORDER`` for
         the strategy's language and picking the first adapter whose
         introspected kind set contains ``kind``.
      2. Fall back to ``_DEFAULT_SOURCE_SERVER_BY_LANGUAGE`` if no adapter
         advertises ``kind`` (e.g. ``refactor`` is in
         ``PythonStrategy.code_action_allow_list`` as a parent kind but
         no adapter advertises the bare ``refactor`` literal).

    See module-level docstring for the rationale on static introspection.

    :param strategy_registry: ``{Language: StrategyClass}`` from Stage 1E.
        ``None`` is treated as an empty mapping (catalog has zero records).
    :param project_root: reserved for T8 of Stage 1G when per-project
        capability gating lands; ignored at MVP.
    """
    del project_root
    if strategy_registry is None:
        return CapabilityCatalog(records=())

    legal_servers = set(get_args(ProvenanceLiteral))
    adapter_map = _adapter_map()

    # Cache one introspection per adapter class — calling
    # _get_initialize_params for every (strategy, kind) pair is wasteful.
    introspected: dict[ProvenanceLiteral, frozenset[str]] = {}
    for server_id, adapter_cls in adapter_map.items():
        introspected[server_id] = _introspect_adapter_kinds(
            adapter_cls, repository_absolute_path="/tmp/_stage_1f_introspect"
        )

    records: list[CapabilityRecord] = []
    for _, strategy_cls in strategy_registry.items():
        language_id = strategy_cls.language_id
        default_server = _DEFAULT_SOURCE_SERVER_BY_LANGUAGE.get(language_id)
        if default_server is None or default_server not in legal_servers:
            raise ValueError(
                f"capability catalog: no default source_server registered "
                f"for language_id={language_id!r}; add it to "
                f"_DEFAULT_SOURCE_SERVER_BY_LANGUAGE"
            )
        attribution_order = _ADAPTER_ATTRIBUTION_ORDER.get(
            language_id, (default_server,)
        )
        for kind in strategy_cls.code_action_allow_list:
            attributed: ProvenanceLiteral = default_server
            for server_id in attribution_order:
                if kind in introspected.get(server_id, frozenset()):
                    attributed = server_id
                    break
            records.append(
                CapabilityRecord(
                    id=f"{language_id}.{kind}",
                    language=language_id,
                    kind=kind,
                    source_server=attributed,
                    params_schema={},
                    preferred_facade=None,
                    extension_allow_list=strategy_cls.extension_allow_list,
                )
            )
    return CapabilityCatalog(records=tuple(records))

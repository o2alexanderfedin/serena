"""
B5 — DynamicCapabilityRegistry merge invariants.

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B B5
regression: dynamic-lsp-capability-complete (parent 8cf3b09)

Properties:
  1. Idempotence: register(server, id, method) twice = register once —
     same supported set via ``has()``.
  2. Order invariance: register(r1, r2, ...) in any order → same
     supported set (registrations are an unordered set keyed by id).

API notes (from solidlsp.dynamic_capabilities):
  - ``register(server_id, registration_id, method, register_options=None)``
  - ``has(server_id, method) -> bool``
  - ``unregister(server_id, registration_id)`` — idempotent
  - Registry is keyed by ``registration_id``, so re-registering the same
    id with the same method is an overwrite (idempotent); different ids
    may carry the same method (multi-registration scenario).
"""

from __future__ import annotations

import string

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from solidlsp.dynamic_capabilities import DynamicCapabilityRegistry

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

METHOD_POOL = [
    "textDocument/codeAction",
    "textDocument/rename",
    "textDocument/codeAction/resolve",
    "textDocument/definition",
    "textDocument/references",
    "textDocument/implementation",
    "textDocument/typeDefinition",
    "workspace/executeCommand",
]

SERVER_POOL = ["basedpyright", "pylsp-base", "ruff", "rust-analyzer"]

method_st = st.sampled_from(METHOD_POOL)
server_st = st.sampled_from(SERVER_POOL)

# A registration is (registration_id, method); registration_id must be unique
# within a server to avoid unintended overwrites in the order-invariance test.
# We build lists of (unique_id, method) pairs.
_reg_id_st = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=4, max_size=12)

registration_st = st.tuples(_reg_id_st, method_st)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _supported_set(reg: DynamicCapabilityRegistry, server_id: str, methods: list[str]) -> frozenset[str]:
    """Return the set of methods that ``has()`` reports as supported."""
    return frozenset(m for m in methods if reg.has(server_id, m))


# ---------------------------------------------------------------------------
# Property 1: Idempotence
# ---------------------------------------------------------------------------


@given(
    server_id=server_st,
    registrations=st.lists(registration_st, min_size=1, max_size=10),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_register_is_idempotent(server_id: str, registrations: list[tuple[str, str]]) -> None:
    """Registering each (id, method) pair twice yields the same ``has()`` set as once."""
    reg_once = DynamicCapabilityRegistry()
    reg_twice = DynamicCapabilityRegistry()

    for reg_id, method in registrations:
        reg_once.register(server_id, reg_id, method)

    for reg_id, method in registrations:
        reg_twice.register(server_id, reg_id, method)
        reg_twice.register(server_id, reg_id, method)  # second call: overwrite same id

    all_methods = [m for _, m in registrations]

    once_supported = _supported_set(reg_once, server_id, all_methods)
    twice_supported = _supported_set(reg_twice, server_id, all_methods)
    assert once_supported == twice_supported, (
        f"Idempotence violated for server={server_id!r}: "
        f"once={once_supported!r}, twice={twice_supported!r}"
    )


# ---------------------------------------------------------------------------
# Property 2: Order invariance
# ---------------------------------------------------------------------------


@given(
    server_id=server_st,
    registrations=st.lists(
        st.tuples(_reg_id_st, method_st),
        min_size=2,
        max_size=10,
    ).filter(lambda rs: len({rid for rid, _ in rs}) == len(rs)),  # unique ids
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.too_slow])
def test_register_is_order_invariant(server_id: str, registrations: list[tuple[str, str]]) -> None:
    """Registration order does not affect the final supported set.

    Forward order vs reversed order must produce identical ``has()`` results
    across the full method pool.
    """
    reg_forward = DynamicCapabilityRegistry()
    reg_reversed = DynamicCapabilityRegistry()

    for reg_id, method in registrations:
        reg_forward.register(server_id, reg_id, method)
    for reg_id, method in reversed(registrations):
        reg_reversed.register(server_id, reg_id, method)

    all_methods = METHOD_POOL  # probe the full method space

    fwd_supported = _supported_set(reg_forward, server_id, all_methods)
    rev_supported = _supported_set(reg_reversed, server_id, all_methods)
    assert fwd_supported == rev_supported, (
        f"Order-invariance violated for server={server_id!r}: "
        f"forward={fwd_supported!r}, reversed={rev_supported!r}"
    )


# ---------------------------------------------------------------------------
# Property 3: Server isolation — registrations never bleed across servers
# ---------------------------------------------------------------------------


@given(
    server_a=server_st,
    server_b=server_st.filter(lambda s: s != "basedpyright"),  # ensure some variety
    method_a=method_st,
    method_b=method_st,
)
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_server_isolation(server_a: str, server_b: str, method_a: str, method_b: str) -> None:
    """A registration on server_a must not bleed into server_b queries."""
    if server_a == server_b:
        return  # skip when Hypothesis picks same server — trivially satisfied

    reg = DynamicCapabilityRegistry()
    reg.register(server_a, "iso-reg-1", method_a)

    # server_b has no registrations — must not see method_a
    assert not reg.has(server_b, method_a), (
        f"Isolation violated: server_a={server_a!r} method={method_a!r} "
        f"leaked into server_b={server_b!r}"
    )

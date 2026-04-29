"""calcpy_circular — Stage 1H Leaf 02 / T11 Module 7 fixture.

Two modules ``a.py`` and ``b.py`` mutually depend on each other through
function-scope (lazy) imports. Promoting either lazy import to module-top
would trigger ImportError at ``python -c 'import calcpy_circular.a'``.

The multi-server circular-import-detection invariant test asserts that
no auto-apply flow promotes the lazy import to module top.
"""

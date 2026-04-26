"""Hide the fixture trees from pytest collection.

The `tests/test_byte_identity.py` files under
`test/e2e/fixtures/calcpy_e2e/` and `test/e2e/fixtures/calcrs_e2e/`
are fixture content that is meant to be run via subprocess after
the fixture has been copied to a temp dir — not collected by the
parent pytest session.
"""

collect_ignore_glob = ["calcpy_e2e/*", "calcrs_e2e/*"]

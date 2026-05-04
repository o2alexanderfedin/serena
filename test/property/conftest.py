"""
Phase B property-test infrastructure.

regression: docs/superpowers/specs/2026-05-03-test-coverage-strategy-design.md §6 Phase B

Hypothesis is configured with two profiles:

- ``ci`` — derandomized + no deadline. Used in CI under ``coverage.yml``.
  Stable across runs (no flake from random seeds); generated cases are
  deterministic so coverage diff-cover compares apples-to-apples.

- ``nightly`` — full-random + larger example budget. Used in the future
  Phase C nightly mutation-testing matrix to surface latent invariants.

Selected via ``HYPOTHESIS_PROFILE`` env var; defaults to ``ci``.
"""

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    derandomize=True,
    deadline=None,
    max_examples=50,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.register_profile(
    "nightly",
    deadline=None,
    max_examples=500,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))

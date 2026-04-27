"""Default disk root resolver for v1.1 persistent checkpoints.

The production ``ScalpelRuntime.checkpoint_store()`` factory MUST pass a
``disk_root`` to ``CheckpointStore`` so checkpoints survive process
restart (Leaf 06 depends on this — see spec line 174-178). This module
is the single source of truth for that root.

Resolution order:

1. ``O2_SCALPEL_CACHE`` env var (consumer-overridable; matches the
   ``${O2_SCALPEL_CACHE}/checkpoints/`` path documented in the v1.1
   spec). Trailing/leading whitespace is stripped; blank values are
   treated as "not set" so users cannot accidentally short-circuit
   the default with an empty export.
2. ``platformdirs.user_cache_dir("o2-scalpel")``. ``platformdirs``
   chooses the OS-correct cache directory (``~/Library/Caches/o2-scalpel``
   on macOS, ``~/.cache/o2-scalpel`` on Linux, ``%LOCALAPPDATA%`` on
   Windows). ``platformdirs`` is a transitive dep already pinned in
   ``uv.lock``; the import is therefore safe.

Returns an absolute ``Path`` rooted at ``<cache>/checkpoints``. Does
NOT create the directory — that is left to ``DiskCheckpointStore``
which creates lazily via ``mkdir(parents=True, exist_ok=True)``.
"""

from __future__ import annotations

import os
from pathlib import Path

import platformdirs

# Env var the user sets to override the platformdirs default.
O2_SCALPEL_CACHE_ENV = "O2_SCALPEL_CACHE"

# Application name used for the platformdirs lookup. Matches the
# Codebase convention used elsewhere (see docs/superpowers/plans/
# 2026-04-26-v11-milestone/02-persistent-disk-checkpoints.md spec).
_APP_NAME = "o2-scalpel"

# Subdirectory under the cache root that holds checkpoint JSON files.
_CHECKPOINTS_SUBDIR = "checkpoints"


def default_checkpoint_disk_root() -> Path:
    """Resolve the production ``CheckpointStore.disk_root`` default.

    Priority: ``O2_SCALPEL_CACHE`` env var → platformdirs user cache.
    Always returns an absolute path; the directory may not yet exist.
    """
    raw = os.environ.get(O2_SCALPEL_CACHE_ENV, "")
    if raw and raw.strip():
        cache_root = Path(raw.strip())
    else:
        cache_root = Path(platformdirs.user_cache_dir(_APP_NAME))
    # Anchor to absolute even if the env var supplied a relative path.
    return (cache_root / _CHECKPOINTS_SUBDIR).resolve()

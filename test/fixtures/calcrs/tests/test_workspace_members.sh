#!/usr/bin/env bash
# Verify all expected RA companion crates are declared as workspace members.
# Stage 1H continuation Leaf 01 (T2): 19 new crates added to the calcrs fixture.
set -euo pipefail
cd "$(dirname "$0")/.."

expected_crates=(
    "ra_extractors"
    "ra_inliners"
    "ra_visibility"
    "ra_imports"
    "ra_glob_imports"
    "ra_ordering"
    "ra_generators_traits"
    "ra_generators_methods"
    "ra_convert_typeshape"
    "ra_convert_returntype"
    "ra_pattern_destructuring"
)

actual=$(CARGO_BUILD_RUSTC=rustc cargo metadata --format-version 1 --no-deps \
  | python3 -c "import json,sys; print('\n'.join(p['name'] for p in json.load(sys.stdin)['packages']))")

missing=0
for crate in "${expected_crates[@]}"; do
    if echo "$actual" | grep -qx "$crate"; then
        echo "OK: $crate present"
    else
        echo "missing crate: $crate"
        missing=1
    fi
done

exit "$missing"

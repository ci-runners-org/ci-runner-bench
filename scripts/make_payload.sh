#!/usr/bin/env bash
# Build the fixed cache-throughput payload. Run from seed.yml only.
# The payload is incompressible, so restore time reflects real transfer cost
# rather than a compression artefact.
set -euo pipefail

source "$GITHUB_WORKSPACE/workloads.lock"
DEST="$HOME/.bench-cache/payload"

mkdir -p "$DEST"
dd if=/dev/urandom of="$DEST/blob" bs=1M count="$CACHE_PAYLOAD_MB" status=none
du -sm "$DEST"

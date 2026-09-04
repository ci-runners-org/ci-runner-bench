#!/usr/bin/env bash
# Image pull throughput. Claim N2 "image pulls in seconds rather than minutes".
set -euo pipefail
source "$GITHUB_WORKSPACE/workloads.lock"
docker image rm "$PULL_IMAGE" >/dev/null 2>&1 || true
t0=$(date +%s.%N)
docker pull -q "$PULL_IMAGE"
t1=$(date +%s.%N)
bytes=$(docker image inspect "$PULL_IMAGE" --format '{{.Size}}')
python3 - "$t0" "$t1" "$bytes" <<'PY'
import sys, json
t0, t1, b = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3])
d = round(t1 - t0, 3)
print(json.dumps({"image_pull_s": d,
                  "image_size_mb": round(b / 1048576, 1),
                  "image_pull_mbps": round(b / 1048576 / d, 1) if d > 0 else None}))
PY

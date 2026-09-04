#!/usr/bin/env bash
# Run one benchmark workload. Every runner executes the identical command set.
# Usage: run_workload.sh <w1|w2|w4|w5>
set -euo pipefail

WL="$1"
source "$GITHUB_WORKSPACE/workloads.lock"
CACHE_ROOT="$HOME/.bench-cache"
mkdir -p "$CACHE_ROOT"

case "$WL" in
  w1)
    export YARN_CACHE_FOLDER="$CACHE_ROOT/yarn"
    cd "$GITHUB_WORKSPACE/work"
    yarn install --frozen-lockfile --network-timeout 600000
    yarn test:typecheck
    yarn test:app
    ;;

  w2)
    export CARGO_HOME="$CACHE_ROOT/cargo"
    # The target directory stays outside the cached tree on purpose. Caching it
    # would push the repository past GitHub's 10 GB cache limit and evict the
    # warm seeds. Compile work is then constant across the cold and warm arms,
    # which isolates CPU for the speed claims.
    export CARGO_TARGET_DIR="$RUNNER_TEMP/cargo-target"
    cd "$GITHUB_WORKSPACE/work"
    cargo build --release --locked
    cargo test --release --locked
    ;;

  w4)
    cd "$GITHUB_WORKSPACE/workloads/w4"
    # One changed byte per run forces a rebuild of the final layer while the
    # dependency layer stays cacheable. This is the churn the design calls for.
    echo "run ${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}" > churn.txt
    # Cold uses a scope that cannot exist yet, so the layer cache always
    # misses. Warm uses the fixed scope that seed.yml populated.
    if [ "${CACHE_MODE:-warm}" = "cold" ]; then
      SCOPE="w4-cold-${GITHUB_RUN_ID}"
    else
      SCOPE="w4"
    fi
    docker buildx build \
      --cache-from "type=gha,scope=${SCOPE}" \
      --cache-to   "type=gha,scope=${SCOPE},mode=max" \
      --load -t bench-w4:local .
    ;;

  w5)
    # No network install. Only the Python that every runner image ships.
    cd "$GITHUB_WORKSPACE/workloads/w5"
    python3 run.py
    ;;

  *) echo "unknown workload: $WL" >&2; exit 2 ;;
esac

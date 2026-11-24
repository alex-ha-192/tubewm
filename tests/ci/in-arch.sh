#!/usr/bin/env bash
# Run the CI checks on your own machine in a fresh Arch Linux container, with
# the same current packages CI uses. Needs docker or podman.
#
#   tests/ci/in-arch.sh                  everything
#   tests/ci/in-arch.sh smoke-session.sh just one check
set -euo pipefail
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
engine=$(command -v podman || command -v docker) || { echo "need podman or docker" >&2; exit 1; }
check=${1:-run-all.sh}
exec "$engine" run --rm -t -v "$repo:/src:ro" archlinux:latest bash -c "
    cp -r /src /repo && cd /repo &&
    tests/ci/arch-deps.sh >/dev/null && tests/ci/$check"

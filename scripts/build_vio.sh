#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUTPUT_ROOT=${OUTPUT_ROOT:-$root/build-vio} BUILD_DIR=${BUILD_DIR:-$root/build-vio/cmake} JOBS=${JOBS:-4} bash "$root/scripts/build_prepared.sh"
